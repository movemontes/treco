// Tradutor do próprio Mac (framework Translation), sem internet.
// O Treco chama este programa porque a tradução da Apple só existe em Swift.
//
//   treco-translate status <de> <para>      -> installed | supported | unsupported
//   treco-translate detect                  (texto na entrada) -> código do idioma
//   treco-translate run <de|auto> <para>    (JSON com lista de textos na entrada) -> JSON com a lista traduzida
//
// Saídas com erro: 3 = idiomas não baixados, 4 = o texto já está nesse idioma,
// 5 = par de idiomas sem suporte, 2 = outro problema.
//
// Compilar: swiftc -parse-as-library -O treco-translate.swift -o ../bin/treco-translate
import Foundation
import NaturalLanguage
import Translation

func fail(_ code: Int32, _ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

func readInput() -> String {
    String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
}

func detect(_ text: String) -> String? {
    let recognizer = NLLanguageRecognizer()
    recognizer.processString(String(text.prefix(4000)))
    return recognizer.dominantLanguage?.rawValue
}

func base(_ code: String) -> String {
    Locale.Language(identifier: code).languageCode?.identifier ?? code
}

@main
struct Main {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { fail(2, "uso: status | detect | run") }
        switch args[1] {
        case "detect":
            print(detect(readInput()) ?? "")
        case "status":
            guard args.count >= 4 else { fail(2, "uso: status <de> <para>") }
            let status = await LanguageAvailability().status(
                from: Locale.Language(identifier: args[2]), to: Locale.Language(identifier: args[3]))
            switch status {
            case .installed: print("installed")
            case .supported: print("supported")
            default: print("unsupported")
            }
        case "run":
            guard args.count >= 4 else { fail(2, "uso: run <de|auto> <para>") }
            guard let texts = try? JSONDecoder().decode([String].self, from: Data(readInput().utf8)) else {
                fail(2, "entrada inválida")
            }
            var source = args[2]
            if source == "auto" {
                guard let found = detect(texts.joined(separator: "\n")) else { fail(2, "idioma não reconhecido") }
                source = found
            }
            let target = args[3]
            if base(source) == base(target) { fail(4, "mesmo idioma \(source)") }
            let from = Locale.Language(identifier: source), to = Locale.Language(identifier: target)
            let status = await LanguageAvailability().status(from: from, to: to)
            if status == .unsupported { fail(5, "sem suporte \(source) \(target)") }
            if status == .supported { fail(3, "não baixado \(source) \(target)") }
            var output = texts
            let requests = texts.enumerated().compactMap { index, text in
                text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? nil : TranslationSession.Request(sourceText: text, clientIdentifier: String(index))
            }
            do {
                let session = TranslationSession(installedSource: from, target: to)
                // em partes, para não pedir tudo de uma vez num arquivo grande
                var start = 0
                while start < requests.count {
                    let part = Array(requests[start..<min(start + 64, requests.count)])
                    for response in try await session.translations(from: part) {
                        if let id = response.clientIdentifier, let index = Int(id) {
                            output[index] = response.targetText
                        }
                    }
                    start += 64
                    FileHandle.standardError.write("progresso \(min(start, requests.count)) \(requests.count)\n".data(using: .utf8)!)
                }
            } catch TranslationError.notInstalled {
                fail(3, "não baixado \(source) \(target)")
            } catch {
                fail(2, error.localizedDescription)
            }
            let data = try! JSONEncoder().encode(output)
            FileHandle.standardOutput.write(data)
        default:
            fail(2, "comando desconhecido")
        }
    }
}
