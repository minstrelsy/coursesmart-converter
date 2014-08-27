# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import unicode_literals

import pdfmadness
from pdfmadness import PdfFile, PdfProp, PdfFontGlyph
from lxml import etree
from cStringIO import StringIO
from itertools import ifilter
import base64
from PIL import Image
import io
import sh
import subprocess
import os
import tempfile
import sys
import zipfile
import os.path
import zlib
import struct
import sys
import objgraph
import gc

from pympler import muppy, summary

from PyPDF2 import PdfFileMerger

class SwfPdf(object):

	def __init__(self):
		self.pdf = PdfFile()
		self.pages = []
		self.swfs = []
		pass

	#@profile
	def add_swf(self, swf_file):

		sxml = SwfXml(swf_file)
		self.pages.append(sxml.id)
		sxml.make(self.pdf)
		pass

	def write(self, fs):

		self.pdf.add_object(name="catalog", props=[
			PdfProp("Type", "/Catalog"),
			PdfProp("Pages", "<%pages%>")
		])
		self.pdf.add_object(name="pages", props=[
			PdfProp("Type", "/Pages"),
			PdfProp("Kids", "[{}]".format(" ".join(map(lambda x: "<%page-{}%>".format(x), self.pages)))),
			PdfProp("Count", "{}".format(len(self.pages)))
		])

		self.pdf.root = "catalog"

		self.pdf.write(fs)
		fs.flush()


class SwfXml(object):

	ignored_tags = { 'FileAttributes', 'SetBackgroundColor', 'CSMTextSettings', 'ShowFrame', 'End' }
	current_id = 0

	#@profile
	def __init__(self, xml):


		self.font_resources = []
		self.image_resources = []
		self.id = SwfXml.current_id
		SwfXml.current_id += 1

		parser = etree.XMLParser(remove_blank_text=True, ns_clean=True)
		swf_xml = etree.fromstring(xml, parser)

		size_rect = swf_xml.find('./Header/size/Rectangle')


		self.width = int(size_rect.get('right'))
		self.height = int(size_rect.get('bottom'))

		self.page_width = 612
		self.page_height = 792

		self.objects = dict()
		self.place_objects = []
		self.fonts = []

		for tag in swf_xml.find('./Header/tags'):
			if tag.tag == 'DefineFont3':
				self.parse_font(tag)
				pass
			elif tag.tag == 'DefineShape3':
				self.parse_defineshape3(tag)
				pass
			elif tag.tag == 'PlaceObject2':
				self.parse_placeobject2(tag)
				pass
			elif tag.tag =='DefineBitsJPEG2':
				self.parse_definebitsjpeg2(tag)
				pass
			elif tag.tag == 'DefineShape':
				self.parse_defineshape(tag)
				pass
			elif tag.tag == 'DefineText2':
				self.parse_definetext2(tag)
				pass
			elif tag.tag == 'DefineBitsLossless':
				self.parse_definebitslossless(tag)
			else:
				if tag.tag not in SwfXml.ignored_tags:
					print "unparsed tag: {}".format(tag.tag)

		#import pdb; pdb.set_trace()
		#objgraph.show_backrefs([swf_xml], refcounts=True, filename='objgraph.png')


	def scale_x(self, x):
		return x / self.width * self.page_width

	def scale_y(self, y):
		return y / self.height * self.page_height + self.page_height

	def scale_y_raw(self, y):
		return y / self.height * self.page_height

	def scale_y_top(self, y, height):
		return self.page_height - (y / self.height * self.page_height) - self.scale_y_raw(height)

	def scale_y_real(self, y, height):
		return self.page_height - (y / self.height * self.page_height) - height

	def parse_font(self, node):

		obj_id = node.get("objectID")
		font = SwfFont(self, node, obj_id)
		self.objects[obj_id] = font
		self.fonts.append(font)

		pass

	def parse_defineshape3(self, node):

		obj_id = node.get("objectID")
		self.objects[obj_id] = SwfShape(self, node, obj_id)

		pass

	def parse_placeobject2(self, node):

		obj_id = node.get("objectID")
		#self.objects[obj_id] = node
		self.place_objects.append(node)

	def parse_definebitsjpeg2(self, node):

		obj_id = node.get("objectID")
		self.objects[obj_id] = SwfImage(node, obj_id)


	def parse_defineshape(self, node):

		obj_id = node.get("objectID")
		self.objects[obj_id] = SwfImageShape(self, node, obj_id)

		pass

	def parse_definetext2(self, node):

		obj_id = node.get("objectID")
		self.objects[obj_id] = SwfDefineText(self, node, obj_id)

		pass

	def parse_definebitslossless(self, node):

		obj_id = node.get("objectID")
		self.objects[obj_id] = SwfImageLossless(node, obj_id)

		pass


	def make(self, pdf):

		page_instructions = []

		for placer in self.place_objects:

			target_obj_id = placer.get("objectID")
			if not target_obj_id in self.objects:
				print "Target id not found: {}".format(target_obj_id)
				continue

			obj = self.objects[target_obj_id]
			if isinstance(obj, (SwfImageShape, SwfDefineText)):
				obj.write(self, page_instructions, pdf)

		for font in self.fonts:
			font.write(self, page_instructions, pdf)

		pdf.add_object(name="page-{}".format(self.id), props=[
			PdfProp("Type", "/Page"),
			PdfProp("Parent", "<%pages%>"),
			PdfProp("MediaBox", "[0 0 612 792]"),
			PdfProp("Contents", "<%page-{}-contents%>".format(self.id)),
			PdfProp("Resources", "<< /Font << {} >> /XObject << {} >> >>".format(" ".join(self.font_resources), " ".join(self.image_resources))) #/F1 <%font-23%>
		])

		pdf.add_object(name="page-{}-contents".format(self.id), props=[], stream="\n".join(page_instructions))



class SwfDefineText(object):

	def __init__(self, swf, node, obj_id):
		self.id = obj_id

		tranform = node.find('./transform/Transform')

		self.x = int(tranform.get("transX"))
		self.y = int(tranform.get("transY"))

		self.instructions = []

		cur_font = None
		cur_color = None
		cur_font_size = 12
		last_leading = 0

		g = []
		first_record = True

		self.instructions.append("BT")
		self.instructions.append("q")

		for outer_record in node.find('./records'):

			record = outer_record.find('./textString/TextRecord72')

			if record.get("isSetup") != "1": continue


			if "fontRef" in record.attrib:
				cur_font = swf.objects[record.get("fontRef")]

			if "fontHeight" in record.attrib:
				cur_font_size = int(record.get("fontHeight")) / 20

			if record.find('./color') is not None:
				cur_color = record.find('./color/Color')

			section_x = self.x + (int(record.get("x")) if "x" in record.attrib else 0)
			section_y = self.y + (int(record.get("y")) if "y" in record.attrib else 0)

			self.instructions.append("/{} {} Tf".format(cur_font.name, cur_font_size))

			if first_record or ("x" in record.attrib and "y" in record.attrib):
				self.instructions.append("1 0 0 1 {} {} Tm".format(swf.scale_x(section_x), swf.scale_y_real(section_y, 0)))

			text_instr = []

			if last_leading:
				text_instr.append("-{}".format(last_leading))

			for glyph in record.find('./glyphs'):

				if len(cur_font.glyphs) <= int(glyph.get("glyph")): continue

				c = cur_font.glyphs[int(glyph.get("glyph"))].map
				if c < 128:
					text_instr.append("<{:02x}> -{}".format(c, int(glyph.get("advance")) / 2))
					last_leading = int(glyph.get("advance"))

			#if text_instr and "(C)" in text_instr[0]:
			#	print record, text_instr

			self.instructions.append("{} {} {} RG".format(int(cur_color.get("red")) / 255, int(cur_color.get("green")) / 255, int(cur_color.get("blue")) / 255))
			self.instructions.append("{} {} {} rg".format(int(cur_color.get("red")) / 255, int(cur_color.get("green")) / 255, int(cur_color.get("blue")) / 255))


			self.instructions.append("[{}] TJ".format(b" ".join(text_instr)))

			first_record = False

		self.instructions.append("Q")
		self.instructions.append("ET")
		pass

	def write(self, page, page_instructions, pdf):

		page_instructions.extend(self.instructions[:])

		pass

class SwfImageLossless(object):

	def __init__(self, node, obj_id):

		self.id = obj_id

		data_node = node.find('./data/data')

		width = int(node.get('width'))
		height = int(node.get('height'))

		self.size = (width, height)

		format = int(node.get('format'))
		n_colormap = int(node.get('n_colormap'))

		data = io.BytesIO(zlib.decompress(base64.b64decode(data_node.text)))

		image = Image.new("RGB", (width, height))

		color_table = [struct.unpack('<BBB', data.read(3)) for _ in range(n_colormap+1)]

		image.putdata([color_table[struct.unpack('<B', data.read(1))[0]] for _ in range(width) for _ in range(height)])
		self.data = image.tobytes("jpeg", "RGB")


	def write(self, page, page_instructions, pdf):

		pdf.add_object(name="page-{}-img-{}".format(page.id, self.id), props=[
			PdfProp("Subtype", "/Image"),
			PdfProp("Width", self.size[0]),
			PdfProp("Height", self.size[1]),
			PdfProp("Filter", "/DCTDecode"),
			PdfProp("BitsPerComponent", 8),
			PdfProp("ColorSpace", "/DeviceRGB")
		], stream=self.data[:])

		page.image_resources.append("/page-{0}-img-{1} <%page-{0}-img-{1}%>".format(page.id, self.id))

class SwfImage(object):

	def __init__(self, node, obj_id):

		self.id = obj_id

		jpeg_data = bytearray(base64.b64decode(node.find('./data/data').text))
		start_index = jpeg_data.find(b'\xff\xd9\xff\xd8')
		del jpeg_data[start_index:start_index+4]

		self.data = bytes(jpeg_data)
		image = Image.open(io.BytesIO(self.data))

		self.size = image.size

	def write(self, page, page_instructions, pdf):

		pdf.add_object(name="page-{}-img-{}".format(page.id, self.id), props=[
			PdfProp("Subtype", "/Image"),
			PdfProp("Width", self.size[0]),
			PdfProp("Height", self.size[1]),
			PdfProp("Filter", "/DCTDecode"),
			PdfProp("BitsPerComponent", 8),
			PdfProp("ColorSpace", "/DeviceRGB")
		], stream=self.data[:])

		page.image_resources.append("/page-{0}-img-{1} <%page-{0}-img-{1}%>".format(page.id, self.id))


class SwfImageShape(object):

	def __init__(self, swf, node, obj_id):

		self.id = obj_id

		bitmap_node = node.find('./styles/StyleList/fillStyles/ClippedBitmap')
		img_obj_id = bitmap_node.get("objectID")
		self.actual_image = swf.objects[img_obj_id]

		img_rect = node.find('./bounds/Rectangle') 
		img_width = int(img_rect.get("right")) - int(img_rect.get("left"))
		img_height = int(img_rect.get("bottom")) - int(img_rect.get("top"))

		self.instructions = []
		self.instructions.append("q")

		self.instructions.append("{} 0 0 {} {} {} cm".format(swf.scale_x(img_width), swf.scale_y_raw(img_height), swf.scale_x(int(img_rect.get("left"))), swf.scale_y_top(int(img_rect.get("top")), img_height)))
		self.instructions.append("/page-{}-img-{} Do".format(swf.id, img_obj_id))

		self.instructions.append("Q")

	def write(self, page, page_instructions, pdf):
		self.actual_image.write(page, page_instructions, pdf)
		page_instructions.extend(self.instructions[:])


class SwfShape(object):

	def __init__(self, swf, node, obj_id):

		self.id = obj_id

		cur_x = 0
		cur_y = 0
		self.instructions = []
		self.instructions.append("q")

		if node.find('./styles/StyleList/fillStyles/Solid') is not None:
			color_node = node.find('./styles/StyleList/fillStyles/Solid/color/Color')
			self.instructions.append("{} {} {} rg".format(int(color_node.get("red")) / 255, int(color_node.get("green")) / 255, int(color_node.get("blue")) / 255))

		if node.find('./styles.StyleList.lineStyles.LineStyle') is not None:
			line_node = node.find('./styles/StyleList/lineStyles/LineStyle')
			if "width" in line_node.attrib:
				self.instructions.append("{} w".format(line_node.get("width")))

			line_color_node = line_node.find('./color/Color')

			self.instructions.append("{} {} {} RG".format(int(color_node.get("red")) / 255, int(color_node.get("green")) / 255, int(color_node.get("blue")) / 255))

		for edge in node.find('./shapes/Shape/edges'):

			if edge.tag == 'ShapeSetup':
				if 'x' in edge.attrib and 'y' in edge.attrib:
					cur_x = int(edge.get("x"))
					cur_y = -int(edge.get("y"))
					self.instructions.append("{} {} m".format(swf.scale_x(cur_x), swf.scale_y(cur_y)))
			elif edge.tag == 'LineTo':
				cur_x += int(edge.get("x"))
				cur_y -= int(edge.get("y"))
				self.instructions.append("{} {} l".format(swf.scale_x(cur_x), swf.scale_y(cur_y)))
			elif edge.tag == 'CurveTo':
				control_point_X = cur_x + int(edge.get("x1"))
				control_point_y = cur_y - int(edge.get("y1"))
				anchor_point_x = control_point_X + int(edge.get("x2"))
				anchor_point_y = control_point_y - int(edge.get("y2"))

				cur_x = anchor_point_x
				cur_y = anchor_point_y
				self.instructions.append("{} {} {} {} v".format(swf.scale_x(control_point_X), swf.scale_y(control_point_y), swf.scale_x(anchor_point_x), swf.scale_y(anchor_point_y)))


		self.instructions.append("b")
		self.instructions.append("Q")

	def write(self, page, page_instructions, pdf):
		page_instructions.extend(self.instructions[:])



class SwfFont(object):

	def __init__(self, swf, node, font_id):

		self.id = font_id

		self.name = node.get('name')
		self.glyphs = dict()

		self.advances = []
		for advance in node.find('./advance'):
			self.advances.append(int(advance.get("value")))

		self.glyphs = []
		for i, glyph in enumerate(node.find('./glyphs')):
			swf_glyph = SwfGlyph(glyph, self.advances[i])
			if swf_glyph.map > 127: continue

			self.glyphs.append(swf_glyph)


	def write(self, page, page_instructions, pdf):

		font = pdf.font_collection.add_font(self.name)

		for glyph in self.glyphs:
			font.add_glyph(PdfFontGlyph("\n".join(glyph.instructions), glyph.map, glyph.advance))

		page.font_resources.append("/{0} <%{0}%>".format(self.name))

		pass



class SwfGlyph(object):

	def __init__(self, node, advance):

		self.advance = advance
		self.map = int(node.get("map"))

		cur_x = 0
		cur_y = 0
		self.instructions = []
		self.instructions.append("{} 0 0 0 750 750 d1".format(self.advance / 20))
		self.instructions.append("q")

		for edge in node.find('./GlyphShape/edges'):
			if edge.tag == 'ShapeSetup':
				if 'x' in edge.attrib and 'y' in edge.attrib:
					cur_x = int(edge.get("x"))
					cur_y = -int(edge.get("y"))
					self.instructions.append("{} {} m".format(cur_x / 20, cur_y / 20))
			elif edge.tag == 'LineTo':
				cur_x += int(edge.get("x"))
				cur_y -= int(edge.get("y"))
				self.instructions.append("{} {} l".format(cur_x / 20, cur_y / 20))
			elif edge.tag == 'CurveTo':
				control_point_X = cur_x + int(edge.get("x1"))
				control_point_y = cur_y - int(edge.get("y1"))
				anchor_point_x = control_point_X + int(edge.get("x2"))
				anchor_point_y = control_point_y - int(edge.get("y2"))

				cur_x = anchor_point_x
				cur_y = anchor_point_y
				self.instructions.append("{} {} {} {} v".format(control_point_X / 20, control_point_y / 20, anchor_point_x / 20, anchor_point_y / 20))


		self.instructions.append("f")
		self.instructions.append("Q")

	def __str__(self):

		return "\n".join(self.instructions)

#@profile
def main():
	package = zipfile.ZipFile(sys.argv[1])

	metadata = []
	with package.open("metadata.txt") as metadata_file:
		metadata.extend(map(str.strip, metadata_file)[:])

	merger = PdfFileMerger()
	swf_pdf = SwfPdf()

	i = 0

	for name in metadata:
		#name = metadata[0]
		i += 1
		print i, name

		single_page = package.read("pages/{}".format(name))
		swfxml_process = subprocess.Popen(['swfmill', 'swf2xml', 'stdin', 'stdout'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
		xml = swfxml_process.communicate(single_page)[0]
		swf_pdf.add_swf(xml)


	output = open("output.pdf", "wb")
	swf_pdf.write(output)
	output.flush()
	output.close()

	return

	sh.qpdf("--object-streams=generate", "output.pdf", "output.compressed.pdf")

main()