package com.enconomy.pop

/** jsQR default export: (Uint8ClampedArray rgba, w, h) -> {data} | null. Handed to pop-qr.js when BarcodeDetector is missing. */
@JsModule("jsqr")
external fun jsQR(data: JsAny, width: Int, height: Int): JsAny?

/** qrcode-generator default export: qrcode(typeNumber, errorCorrectionLevel). */
@JsModule("qrcode-generator")
external fun qrcode(typeNumber: Int, errorCorrectionLevel: String): JsAny
