import StringIO
import re

class PdfFile(object):

	def __init__(self):
		self.objects = []
		self.lookup = dict()
		self.current_id = 1
		self.root = None

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
