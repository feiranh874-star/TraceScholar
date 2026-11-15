import Foundation
import Vision
import AppKit

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US", "zh-Hans"]
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(url: url)
do {
    try handler.perform([request])
    let observations = (request.results ?? []).sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.012 {
            return $0.boundingBox.midY > $1.boundingBox.midY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }
    print(observations.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n"))
} catch {
    fputs("OCR recognition failed\n", stderr)
    exit(1)
}
