(function(window, $){

	$.when($.getScript("http://cdnjs.cloudflare.com/ajax/libs/jszip/2.3.0/jszip.min.js"),
	 $.getScript("//cdn.jsdelivr.net/filesaver.js/0.2/FileSaver.min.js"),
	 $.getScript("https://rawgit.com/yaegaki/binaryReader.js/master/binaryReader.js")
	).done(begin);

	function decompress(t) {
		if (String.isNullOrEmpty(t)) {
			return t;
		}
		var buffer = "";
		var c = " ";
		var n = 0;
		var end = false;
		var start = false;
		var $5 = false;
		var j = t.length;
		var regex = new RegExp("\"|\\\\'", "g");

		var tokenizeEvaluate = function(value) {
			return value === '"' ? '\\"' : "'";
		};
		for (; n < j;) {
			if ($5) {
				var i = n;
				var inString = false;
				var callback = c;
				for (; i < j;) {
					c = t.charAt(i);
					if (!inString && c === callback) {
						break;
					}
					inString = c === "\\" && !inString;
					i++;
				}
				if (i < j) {
					var text = t.substr(n, i - n);
					if (callback === "'") {
						text = text.replace(regex, tokenizeEvaluate);
					}
					buffer += text + '"';
					$5 = false;
					end = false;
					start = false;
				}
				n = i;
			} else {
				c = t.charAt(n);
				if (c === '"' || c === "'") {
					buffer += '"';
					$5 = true;
				} else {
					if ((end || start) && c === ",") {
						buffer += '"",';
					} else {
						if (end && c === "]") {
							buffer += '""]';
						} else {
							buffer += c;
						}
					}
					end = c === ",";
					start = c === "[";
				}
			}
			n++;
		}
		return buffer;
	}

	function begin() {
		var localcontent = window.localStorage.getItem("coursesmartreader");
		var localobj = JSON.parse(localcontent);

		Object.keys(localobj).forEach(function(userId) {
			var userObj = localobj[userId];
			Object.keys(userObj.books).forEach(function(bookId) {
				process(userId, bookId);
			})
		});

		function get(url, params) {


			if(params.length) url += "?"
			var paramString = [];
			params.forEach(function(p) {
				paramString.push(p[0] + "=" + p[1]);
			});

			url += paramString.join("&");

			return new Promise(function(resolve, reject) {
				$.get(url).then(function(data) {
					resolve(data);
				}).error(function(err) {
					reject(err);
				});
			});
		}

		function getPage(id) {
			return new Promise(function(resolve, reject) {
				var xhr = new XMLHttpRequest();
				xhr.onreadystatechange = function(){
				    if (this.readyState == 4 && this.status == 200){
				        resolve({
				        	id: id,
				        	response: this.response
				        });
				    }
				}
				xhr.open('GET', "http://www.coursesmart.com/getofflineflashpage/" + id + 'Z');
				xhr.responseType = 'arraybuffer';
				xhr.send();
			});
		}

		function decrypt(file) {
			"use strict";

			var data = new binaryReader(new Uint8Array(file));

			var operation = data.readUint8();
			switch(operation) {
				case 2:
					//read 6 bytes to skip unneeded parts
					data.readBytes(6);
					break;
				case 3:
					var numPairs = data.readUint16();
					for(var i = 0; i < numPairs; i++) {
						var keyLength = data.readUint16();
						var key = data.readAsciiString(keyLength);

						var valueLength = data.readUint16();
						var value = data.readAsciiString(valueLength);
					}
					break;
			}

			var XORKeyLength = data.readUint8();
			var SPECIAL = data.readUint8();
			var swapTableLength = data.readUint8();

			var XORKey = data.readBytes(XORKeyLength);
			var swapTable = data.readBytes(swapTableLength);

			var movieDataLength = data.data.length - data.position;
			var smallerBytesToSwap = (movieDataLength / SPECIAL) | 0;
			var largerBytesToSwap = (movieDataLength - (smallerBytesToSwap * (SPECIAL - 1))) | 0;

			var dataBytes = data.readBytes(movieDataLength);
			for(var i = 0; i < dataBytes.length; i++) {
				dataBytes[i] = dataBytes[i] ^ XORKey[i % XORKeyLength];
			}

			for(var i = swapTableLength - 1; i >= 0; i--) {
				var swapValue = swapTable[i];

				if(swapValue != i) {
					var bytesToSwap1 = (swapValue == (SPECIAL - 1)) ? largerBytesToSwap : smallerBytesToSwap;
					var bytesToSwap2 = (i == (SPECIAL - 1)) ? largerBytesToSwap : smallerBytesToSwap;
					var bytesToSwap = Math.min(bytesToSwap1, bytesToSwap2);

					var secondSwapPosition = swapValue * smallerBytesToSwap; 
					var firstSwapPosition = i * smallerBytesToSwap;

					var firstSwapBuffer = new Uint8Array(dataBytes.subarray(firstSwapPosition, firstSwapPosition + bytesToSwap));
					var secondSwapBuffer = new Uint8Array(dataBytes.subarray(secondSwapPosition, secondSwapPosition + bytesToSwap));

					dataBytes.set(secondSwapBuffer, firstSwapPosition);
					dataBytes.set(firstSwapBuffer, secondSwapPosition);

				}
			}

			return dataBytes.buffer;

		}

		function process(userId, bookId) {

			var pages, offlineTocObj;

			get("http://www.coursesmart.com/blank", [
				["__className", "smartreaderavailableofflinetoc"],
				["userid", userId],
				["offline", 1],
				["xmlid", bookId]
			]).then(function(availableToc) {

				offlineTocObj = JSON.parse($(availableToc).find("OfflineTocJSon").html());
				var pages = {};
				offlineTocObj.forEach(function(section) {
					Object.keys(section.pages).forEach(function(pageId) {
						pages[pageId] = section.pages[pageId];
					});
				});

				var numPages = Object.keys(pages).length;
				var flashPageInfos = []
				for(var i = 0; i < numPages; i += 15) {
					flashPageInfos.push(get("http://www.coursesmart.com/offlinegetflashpageinfo", [
						["xmlid", bookId],
						["pageindex", i],
						["offline", 1],
						["userid", userId]
					]));
				}

				return Promise.all(flashPageInfos);

			}).then(function(pageInfos) {

				pages = [];
				pageInfos.forEach(function(info) {
					pages = pages.concat($(info).find("page").map(function(_,e){return $(e).html()}).get());
				});

				return Promise.all(pages.map(getPage));

			}).then(function(pageFiles) {

				pageFiles.forEach(function(page) {
					page.response = decrypt(page.response);
				});

				return pageFiles;

			}).then(function(pageFiles) {

				var zip = new JSZip();
				zip.file("metadata.txt", pages.join('\n'));
				zip.file("toc.json", JSON.stringify(offlineTocObj));
				zip.file("tocNames.json", decompress($("#TOCJSon").val()));

				var pagesFolder = zip.folder("pages");
				pageFiles.forEach(function(page) {
					pagesFolder.file(page.id, page.response);
				});

				var content = zip.generate({ type: "blob" });
				saveAs(content, "package.zip");
			})
		}
	}


})(window, jQuery)
