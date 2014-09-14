Coursesmart Converter
=======

This converts ebooks from coursesmart into a readable pdf format.

###Why?

After looking for some ebooks, some books weren't available as a pdf.  A [previous solution](https://github.com/SpikedCola/DownloadCourseSmartBooks) produced a pdf of hundreds of megabytes, and didn't copy the text.  So I made an swf-to-pdf converter.

###Setup
Clone this repository into a new directory.  Install swfmill using a package manager of your choice.  On ubuntu it's:
```
sudo apt-get install swfmill
```
If you want to minify the resulting pdf, you'll want to install qpdf as well:
```
sudo apt-get install qpdf
```
Then install the python requirements (you'll probably want to do it inside of a virutalenv):
```
pip install -r requirements.txt
```

###Steps

1. Run package.js inside of the offline ebook reader.  It will decrypt and download all needed files into a file named "package.zip"
2. Then run `python make.py package.zip`
3. The resulting pdf will be named `output.pdf`
4. (optional) Minify it further with `qpdf --object-streams=generate output.pdf output.q.pdf`
5. Enjoy your pdf named `output.pdf` or `output.q.pdf`!

###Limitations

1. No support for clipping paths
2. Unicode fonts won't copy correctly
3. Fonts aren't combined and results in a larger pdf
4. Font clipping paths are incorrectly implemented.  The pdf will not look correctly using Adobe products.  (Use sumatrapdf)
5. There are no options and it may fail spectacularly. 