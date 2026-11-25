// Resume textos com a IA do próprio Mac (Apple Intelligence), sem internet.
// Uso:  treco-summarize status
//       treco-summarize run <curto|medio|detalhado>   (texto pela entrada; o resumo sai na saída)
// Saída 3 = IA indisponível (motivo no erro), 6 = o Mac recusou o conteúdo.
// Gerar de novo: swiftc -parse-as-library -O treco-summarize.swift -o ../bin/treco-summarize
import Foundation
import FoundationModels

func fail(_ code: Int32, _ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

func reason() -> String? {
    switch SystemLanguageModel.default.availability {
    case .available: return nil
    case .unavailable(.deviceNotEligible): return "Este Mac não tem Apple Intelligence"
    case .unavailable(.appleIntelligenceNotEnabled): return "Ligue a Apple Intelligence nos Ajustes"
    case .unavailable(.modelNotReady): return "A IA do Mac ainda está baixando. Tente mais tarde"
    default: return "A IA do Mac não está disponível"
    }
}

// idioma do resumo: o 3º argumento ("en" = inglês); sem ele, português
let english = CommandLine.arguments.count > 3 && CommandLine.arguments[3] == "en"

let rules = english ? """
You summarize texts in plain English, with simple and direct sentences.
Only talk about what is in the text, without making anything up and without giving opinions.
Do not use markdown asterisks. For lists, start each line with "- ".
""" : """
Você resume textos em português do Brasil, com frases simples e diretas.
Fale só do que está no texto, sem inventar nada e sem opinar.
Não use markdown com asteriscos. Para listas, comece cada linha com "- ".
"""

// modo feito para resumir/transformar textos: notícias com crimes ou doenças não travam o resumo
let model = SystemLanguageModel(guardrails: .permissiveContentTransformations)

func ask(_ prompt: String) async throws -> String {
    let session = LanguageModelSession(model: model, instructions: rules)
    let answer = try await session.respond(to: prompt, options: GenerationOptions(temperature: 0.3))
    return answer.content.trimmingCharacters(in: .whitespacesAndNewlines)
}

func isTooBig(_ error: Error) -> Bool {
    if let error = error as? LanguageModelSession.GenerationError, case .exceededContextWindowSize = error { return true }
    return false
}

// anota um trecho; se não couber na memória da IA, divide em dois e tenta de novo
func notes(_ part: String) async throws -> [String] {
    do {
        return [try await ask(english ? "Write short bullet notes with the main information in this excerpt:\n\n\(part)" : "Anote em tópicos curtos as informações principais deste trecho:\n\n\(part)")]
    } catch where isTooBig(error) && part.count > 1200 {
        let half = pieces(part, size: part.count / 2 + 1)
        let halves = half.count > 1 ? half : [String(part.prefix(part.count / 2)), String(part.dropFirst(part.count / 2))]
        var out: [String] = []
        for piece in halves { out += try await notes(piece) }
        return out
    }
}

func pieces(_ text: String, size: Int) -> [String] {
    // corta nos parágrafos, em pedaços que cabem na memória da IA
    var parts: [String] = [], current = ""
    for paragraph in text.components(separatedBy: "\n") where !paragraph.trimmingCharacters(in: .whitespaces).isEmpty {
        if current.count + paragraph.count > size && !current.isEmpty {
            parts.append(current); current = ""
        }
        current += String(paragraph.prefix(size)) + "\n"
    }
    if !current.isEmpty { parts.append(current) }
    return parts
}

@main
struct Main {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { fail(2, "uso: treco-summarize status | run <tamanho> [pt|en]") }
        if let why = reason() { fail(3, why) }
        if args[1] == "status" { print("ok"); return }
        let size = args.count > 2 ? args[2] : "medio"
        let text = String(decoding: FileHandle.standardInput.readDataToEndOfFile(), as: UTF8.self)
        if text.trimmingCharacters(in: .whitespacesAndNewlines).count < 80 { fail(4, "Texto curto demais para resumir") }
        let goal: String
        switch size {
        case "curto": goal = english ? "Write a summary of 2 to 3 sentences." : "Escreva um resumo de 2 a 3 frases."
        case "detalhado": goal = english ? "Write an introductory paragraph and then 6 to 10 bullet points with the important points, including numbers and names mentioned." : "Escreva um parágrafo de introdução e depois de 6 a 10 tópicos com os pontos importantes, incluindo números e nomes citados."
        default: goal = english ? "Write a short paragraph and then 3 to 5 bullet points with the main points." : "Escreva um parágrafo curto e depois de 3 a 5 tópicos com os pontos principais."
        }
        do {
            var parts = pieces(text, size: 6000)
            if parts.count > 8 { parts = Array(parts.prefix(8)) }  // textos enormes: as 8 primeiras partes
            var written: [String] = []
            if parts.count == 1 {
                written = [parts[0]]
            } else {
                for (i, part) in parts.enumerated() {
                    FileHandle.standardError.write("parte \(i + 1) \(parts.count)\n".data(using: .utf8)!)
                    written += try await notes(part)
                }
            }
            FileHandle.standardError.write("final\n".data(using: .utf8)!)
            var joined = written.joined(separator: "\n")
            var limit = 8000
            while true {
                if joined.count > limit { joined = String(joined.prefix(limit)) }
                do {
                    print(try await ask("\(goal)\n\n\(english ? "Text" : "Texto"):\n\n\(joined)"))
                    break
                } catch where isTooBig(error) && limit > 1500 {
                    limit = min(limit, joined.count) * 2 / 3  // não coube: usa menos texto
                }
            }
        } catch let error as LanguageModelSession.GenerationError {
            switch error {
            case .guardrailViolation: fail(6, "A IA do Mac se recusou a resumir esse conteúdo")
            case .exceededContextWindowSize: fail(5, "Texto grande demais para a IA do Mac")
            case .assetsUnavailable: fail(3, "A IA do Mac ainda está baixando. Tente mais tarde")
            case .rateLimited, .concurrentRequests: fail(1, "A IA do Mac está ocupada. Tente de novo em instantes")
            case .unsupportedLanguageOrLocale: fail(1, "A IA do Mac não entende o idioma dessa página")
            default: fail(1, "A IA do Mac falhou: \(error.localizedDescription)")
            }
        } catch {
            fail(1, "A IA do Mac falhou: \(error.localizedDescription)")
        }
    }
}
