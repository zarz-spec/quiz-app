import Foundation
import PDFKit
import Vision
import AppKit

// 用法: swift ocr.swift <pdf路径>   输出识别出的文字
func ocrPDF(_ path: String) -> String {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else {
        return ""
    }
    var result = ""
    for i in 0..<doc.pageCount {
        guard let page = doc.page(at: i) else { continue }
        let w = page.bounds(for: .mediaBox).width * 2.0
        let h = page.bounds(for: .mediaBox).height * 2.0
        let img = page.thumbnail(of: NSSize(width: w, height: h), for: .mediaBox)
        var rect = NSRect(origin: .zero, size: img.size)
        guard let cg = img.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { continue }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true
        let handler = VNImageRequestHandler(cgImage: cg, options: [:])
        do {
            try handler.perform([request])
        } catch {
            continue
        }
        if let obs = request.results {
            for o in obs {
                if let t = o.topCandidates(1).first {
                    result += t.string + "\n"
                }
            }
        }
        result += "\n"
    }
    return result
}

let args = CommandLine.arguments
if args.count >= 2 {
    print(ocrPDF(args[1]))
} else {
    FileHandle.standardError.write("用法: swift ocr.swift <pdf路径>\n".data(using: .utf8)!)
}
