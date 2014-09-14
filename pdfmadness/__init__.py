import StringIO
import re

class PdfFile(object):

	def __init__(self):
		self.objects = []
		self.lookup = dict()
		self.current_id = 1
		self.root = None
		self.font_collection = PdfFontCollection()

	def add_object(self, name=None, props=None, stream=None):
		obj = PdfObject(pdf=self, name=name, props=props, stream=stream, id=self.current_id)
		self.current_id += 1
		self.objects.append(obj)

		if name:
			if name in self.lookup:
				print "duplicate id: {}".format(name)
			self.lookup[name] = obj.id

		pass

	def write(self, fs):

		fs.write("%PDF-1.6\n")

		for font in self.font_collection.fonts.values():
			font.write(self)

		for obj in self.objects:
			obj.write(fs)

		xref_pos = fs.tell()

		self.write_xref(fs)

		fs.write("trailer\n")
		fs.write("<<\n")
		fs.write("/Size {}\n".format(len(self.objects) + 1))
		fs.write("/Root {}\n".format(self.resolve_name(self.root)))
		fs.write(">>\n")
		fs.write("startxref\n")
		fs.write("{}\n".format(xref_pos))
		fs.write("%%EOF")

	def write_xref(self, fs):
		fs.write("xref\n")
		fs.write("0 {}\n".format(len(self.objects) + 1))
		fs.write("0000000000 65535 f \n")
		for obj in self.objects:
			fs.write("{} 00000 n \n".format(str(obj.pos).zfill(10)))

	def resolve_name(self, name):
		if not name in self.lookup:
			print "unresolved name: {}".format(name)
			return "0 0 R"
		return "{} 0 R".format(self.lookup[name])


class PdfObject(object):

	def __init__(self, pdf=None, name=None, props=None, stream=None, id=None):
		self.pdf = pdf
		self.name = name
		self.props = props or []
		self.stream = stream
		self.id = id
		self.pos = 0

	def write(self, fs):
		self.pos = fs.tell()

		fs.write("{} 0 obj\n".format(self.id))
		fs.write("<<\n")
		for prop in self.props:
			prop.write(fs, self.pdf)

		if self.stream:
			fs.write("/Length {}\n".format(len(self.stream)))

		fs.write(">>\n")
		if self.stream:
			fs.write("stream\n")
			fs.write(self.stream)
			fs.write("endstream\n")

		fs.write("endobj\n")
	pass

class PdfProp(object):

	interpolate_regex = re.compile("<%(.*?)%>")

	def __init__(self, name, value):
		self.name = name
		self.value = value

	def write(self, fs, pdf):
		interpolated_value = PdfProp.interpolate_regex.sub(lambda x: pdf.resolve_name(x.group(1)), str(self.value))

		fs.write("/{} {}\n".format(self.name, interpolated_value))

class PdfFontCollection(object):

	def __init__(self):
		self.fonts = dict()

	def add_font(self, name):
		if not name in self.fonts:
			self.fonts[name] = PdfFont(name)
		return self.fonts[name]

	def get_font_names(self, name):
		font = self.fonts[name]
		return map(lambda x: "{}-{}".format(font.name, x), font.get_sections())

class PdfFont(object):

	def __init__(self, name):
		self.name = name
		self.glyph_mapping = dict()

	def add_glyph(self, glyph):
		self.glyph_mapping[glyph.mapping] = glyph

	def get_sections(self):
		names = []
		used_names = set()

		for i in range(1, 65536):
			if i in self.glyph_mapping and i // 256 not in used_names:
				names.append(i // 256)
				used_names.add(i // 256)

		return names

	def write(self, pdf):

		for section in self.get_sections():

			char_procs_props = []
			filled_advances = []
			differences = []
			last_char = -1

			differences.append("0")

			for char in range(section * 256, (section + 1) * 256):
				advance = 0
				char_name = "{}-{}-{}".format(self.name, section, char)

				if char in self.glyph_mapping:
					glyph = self.glyph_mapping[char]

					advance = glyph.advance
					pdf.add_object(name=char_name, stream=glyph.draw_instructions)
					char_procs_props.append(PdfProp(char_name, "<%{}%>".format(char_name)))

					if last_char + 1 != char % 256:
						differences.append("{}".format(char % 256))
						last_char = char % 256
					differences.append("/{}\n".format(char_name))

				#filled_advances.append(0)
				filled_advances.append(advance // 20)

			pdf.add_object(name="{}-{}-char_procs".format(self.name, section), props=char_procs_props)

			pdf.add_object(name="{}-{}-encoding".format(self.name, section), props=[
				PdfProp("Type", "/Encoding"),
				PdfProp("Differences", "[{}]".format(" ".join(differences)))
			])

			pdf.add_object(name="{}-{}-tounicode".format(self.name, section), stream="""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo
<</Registry (Adobe)
/Ordering (UCS)
/Supplement 0
>> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0000> <FFFF> <0000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end""")

			pdf.add_object(name="{}-{}".format(self.name, section), props=[
				PdfProp("Type", "/Font"),
				PdfProp("Subtype", "/Type3"),
				PdfProp("Name", "({}-{})".format(self.name, section)),
				PdfProp("FontBBox", "[0 0 1024 1024]"),
				PdfProp("FontMatrix", "[0.001 0 0 0.001 0 0]"),
				PdfProp("CharProcs", "<%{}-{}-char_procs%>".format(self.name, section)),
				PdfProp("Encoding", "<%{}-{}-encoding%>".format(self.name, section)),
				#PdfProp("ToUnicode", "<%{}-tounicode%>".format(self.name)),
				PdfProp("FirstChar", 0),
				PdfProp("LastChar", 255),
				PdfProp("Widths", "[{}]".format(" ".join(map(str, filled_advances))))
			])


class PdfFontGlyph(object):

	def __init__(self, draw_instructions, mapping, advance):
		self.draw_instructions = draw_instructions
		self.mapping = mapping
		self.advance = advance