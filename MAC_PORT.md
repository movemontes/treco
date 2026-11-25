# Treco: guia para a versão de macOS

Como a versão de macOS do Treco foi feita a partir da de Windows, e as regras que valem para mexer nela. O mesmo código roda nos dois sistemas.

## O que é o Treco

Faz-tudo de arquivos, de uso pessoal e entre amigos (não será vendido). Tudo acontece no computador, sem enviar arquivos para a internet. A única exceção é baixar o modelo de voz na primeira legenda.

- **Converter:** imagem, áudio, vídeo, PDF, documentos e planilhas.
- **Comprimir:** Leve, Médio, Forte ou até um tamanho exato em MB.
- **Editar:** girar, espelhar, inverter, cortar, recortar, tamanho, sem som, acelerar, volume, limpar metadados, juntar e separar.
- **Legendar:** transcreve o vídeo, deixa corrigir, escolher fonte, tamanho, cor e posição, e grava a legenda.
- **Roda do Shift:** segurar Shift ao arrastar um arquivo abre uma roda de ações no cursor.
- **Mini barra de progresso** que segue o mouse.
- **Visual retrô real:** tudo desenhado pixel a pixel, com fonte bitmap, ícones e paleta próprios, sem suavização.

## Como trabalhar

1. Fale em português simples: o dono do projeto não é programador.
2. Faça em etapas e teste cada uma no Mac antes da próxima:
   1. Ambiente e motor (`core/` e `modules/`) rodando pela linha de comando.
   2. Janela principal, janelas de ferramenta e legenda.
   3. Ícone na barra de menus, iniciar com o sistema e barra de progresso.
   4. Roda do Shift no Finder.
   5. Gerar o `.app` e testar fora da pasta do projeto.
3. **Mantenha a versão de Windows funcionando.** Separe o que é específico de cada sistema, por exemplo em `ui/platform_win.py` e `ui/platform_mac.py`, em vez de copiar o projeto.
4. **Nunca simule cliques ou arrastos no mouse real do usuário.** Teste a lógica com cursor e botão falsos e peça para a pessoa fazer o gesto real. Na versão de Windows, um teste assim deixou o botão do mouse preso.
5. Diga claramente o que foi testado de verdade e o que ainda depende de um teste manual.

## Mapa do código

| Caminho | Função | No Mac |
|---|---|---|
| `treco.py` | Ponto de entrada | Mantém |
| `treco_app/core/` | Formatos, nomes de arquivo, tarefas, log | Mantém; ajustar pasta do log |
| `treco_app/modules/` | Conversão, compressão, edição, legenda | Quase tudo mantém; ver abaixo |
| `ui/pixel.py`, `ui/icons.py` | Paleta, fonte bitmap, ícones | Mantém |
| `ui/toolkit.py` | Widgets em pixels | Widgets mantêm; parte nativa da janela muda |
| `ui/window.py`, `caption_editor.py`, `tool_dialogs.py` | Telas | Mantém com ajustes |
| `ui/pill.py` | Barra que segue o mouse | Lógica mantém; janela nativa muda |
| `ui/wheel.py` | Roda do Shift | Regras e desenho mantêm; detecção e janela mudam |
| `ui/tray.py` | Bandeja e início automático | Refazer |
| `ui/winapi.py` | Chamadas do Windows | Criar equivalente para Mac |
| `ui/main.py` | Inicialização | Trocar DPI e instância única |

## Pontos específicos do Windows

- `ui/winapi.py`: `user32`, `gdi32`, janelas em camadas, gancho do mouse, seleção do Explorer via COM.
- `ui/toolkit.py`: `setup_native`, `minimize`, DWM. A janela usa `overrideredirect`, que no macOS pode causar problemas de foco e teclado. Verifique e, se preciso, use o estilo de janela do Tk para Mac.
- `ui/main.py`: mutex, DPI e `.ico`. O app precisa de `.icns`, que pode ser gerado a partir de `mascot()` em `ui/icons.py`.
- `ui/tray.py`: `winreg` e pystray. No Mac, usar a barra de menus e um Login Item ou LaunchAgent.
- `ui/window.py`: `os.startfile` vira `open`.
- `TextField` em `ui/toolkit.py`: colar usa Ctrl+V; no Mac deve ser Cmd+V.
- `creationflags=NO_WINDOW`: já vale 0 fora do Windows, conferir todas as chamadas.
- `core/log.py` e `modules/captions.py`: usam `LOCALAPPDATA`. No Mac, usar `~/Library/Logs/Treco` e `~/Library/Application Support/Treco`.
- `modules/documents.py`: gera PDF com o Microsoft Edge. No Mac, usar Chrome/Edge se existir, LibreOffice se existir, e manter o método interno como alternativa.

### Armadilhas prováveis

- **ffmpeg:** o código usa `shutil.which("ffmpeg")`, mas apps abertos pelo Finder têm um PATH mínimo e não enxergam o Homebrew. Leve o ffmpeg dentro do app ou procure em caminhos conhecidos.
- **Legenda:** exige ffmpeg com o filtro `whisper`, além de `ass`/libass. Confirme com `ffmpeg -filters | grep -E "whisper|ass"`. A versão do Homebrew pode não trazer o `whisper`.
- **Retina:** o Tk trabalha em pontos. Confirme que os pixels continuam quadrados e nítidos, sem borrar.
- **Drag and drop:** confirme que o `tkinterdnd2` traz o binário para a arquitetura do Mac.
- **Python:** prefira uma instalação com Tk moderno. O Tk antigo do sistema pode dar problemas.
- **Versões:** `requirements.txt` traz as versões usadas no Windows. Se alguma não existir no Mac, use a mais próxima e registre a mudança.

## Roda do Shift: comportamento obrigatório

Estas regras vieram de testes reais do dono do projeto:

1. Abre ao arrastar um arquivo do Finder com **Shift** pressionado.
2. A primeira volta mostra só as ações possíveis:
   - Vídeo: Converter, Comprimir, Editar, Legendar.
   - Imagem, áudio e PDF: Converter, Comprimir, Editar.
   - Documento e planilha: Converter.
   - Todos os tipos ganham também **Renomear** (pedido do dono): soltar em cima abre o renomear em lote, sem segunda roda.
3. Ao passar em uma ação, uma **segunda roda contorna a primeira inteira** com as opções, e a primeira fica acinzentada em meio-tom enquanto o mouse está na segunda.
4. **Só executa quando o botão do mouse é realmente solto.** Se o sistema encerrar o arrasto antes, nada acontece e a roda continua seguindo o cursor.
5. Soltar o Shift no meio **não** fecha a roda.
6. Soltar no centro ou fora da roda cancela. **Esc** também cancela.
7. O original **nunca** é movido ou apagado: a operação de arrasto deve ser sempre cópia.
8. A seleção inteira é validada (`selection_problem` em `core/formats.py`):
   - Vários arquivos do mesmo tipo: abre.
   - Qualquer arquivo sem suporte ou pasta: não abre e mostra um aviso perto do mouse.
   - Tipos diferentes, como imagem + vídeo: não abre e mostra um aviso.
   - **Nunca adivinhar o tipo do arquivo.**
9. O texto do centro precisa caber dentro do círculo.
10. Perto da borda, a roda se ajusta para aparecer inteira.

### Caminho sugerido no macOS

Use PyObjC para a parte nativa:

- `NSEvent` para acompanhar movimento, botão e Shift globalmente.
- `NSPasteboard` de arrasto (`NSPasteboardNameDrag`) para ler os arquivos arrastados, sem depender de AppleScript no Finder.
- `NSPanel` sem borda, transparente, sempre no topo e sem roubar o foco, para a roda e a mini barra, exibindo as imagens RGBA que `wheel.py` e `pill.py` já geram.

Confirme no Mac quais permissões de Privacidade e Segurança são realmente necessárias e explique cada uma ao usuário.

## Empacotamento

- Para passar adiante: `.venv/bin/python vendor/build_mac.py` gera `dist/Treco.app` (funciona sozinho, sem Python) e `dist/Treco-<versão>-mac.dmg` (a pessoa arrasta o Treco para Aplicativos). Usa PyInstaller; os programas de `vendor/bin` vão em `Contents/Frameworks/bin`. O modelo de legendas não vai junto: é baixado no primeiro uso. Só para Mac com chip Apple.
- Inclua ffmpeg e pandoc, ou explique o que falta.
- Sem conta de desenvolvedor da Apple, o app não fica notarizado. Explique como liberar em Privacidade e Segurança ao passar para amigos.
- Um app para Apple Silicon não roda nativamente em Mac Intel.
- Para o dia a dia, `vendor/make_mac_app.py` cria um `Treco.app` na pasta do projeto que roda este código com nome, ícone, Dock e menus próprios (sem ele o Mac mostra "Python"). Rode de novo se a pasta mudar de lugar. Não serve para passar a amigos: depende do Python e do `.venv` deste Mac.
- Inclua `segno` (QR Code e QR do Wi-Fi; vale também no Windows) e `numpy` (Escanear: endireitar a folha e tirar a sombra).
- "Limpar Downloads" lê `~/Downloads`: na primeira vez o Mac pergunta se o Treco pode acessar a pasta. Nada é apagado de vez, vai para o Lixo.
- Inclua `vendor/bin/treco-summarize` (resumo de página com a IA do Mac). Para gerar de novo: `cd vendor/src && swiftc -parse-as-library -O treco-summarize.swift -o ../bin/treco-summarize`. Precisa de macOS 26 e Apple Intelligence ligada.
- No `Info.plist`, ponha `NSAppleEventsUsageDescription`: o desinstalador pede ao Finder para apagar apps instalados pela App Store (o Finder pede a senha).
- O histórico de cópias fica em `~/Library/Application Support/Treco/historico de copias.json` (só texto; cópias marcadas como secretas pelos gerenciadores de senha ficam de fora).
- As escolhas do botão direito ficam em `~/Library/Application Support/Treco/ajustes.json`.
- Inclua `vendor/bin/treco-translate` (o tradutor). Para gerar de novo: `cd vendor/src && swiftc -parse-as-library -O treco-translate.swift -o ../bin/treco-translate`. Precisa de macOS 26 ou mais novo. Os idiomas são baixados pela pessoa em Ajustes > Geral > Idioma e Região > Idiomas de Tradução.
- No `Info.plist`, ponha `NSMicrophoneUsageDescription` (gravador de voz e "Tela e voz"). A Gravação de Tela não tem chave: o Mac pergunta na primeira vez e a pessoa libera em Privacidade e Segurança.
- Inclua `pyobjc-framework-Vision` e `pyobjc-framework-Quartz` (Sem fundo, Ler texto, Rostos e a permissão de tela).

## Como conferir o motor

Com as dependências instaladas:

```bash
python3 treco.py --converter foto.png JPG
python3 treco.py --comprimir video.mp4 medio
python3 treco.py --editar video.mp4 espelhar
python3 treco.py --rapido clean foto.jpg
python3 treco.py --legendar video.mp4
```

Estes comandos saem com código 0 quando dá certo e criam um arquivo novo ao lado do original. Hoje `ui/main.py` chama APIs do Windows só depois de tratar a linha de comando, mas `ui/winapi.py` e alguns imports precisam ser isolados para o motor abrir no Mac.

## Pronto significa

- [ ] Todas as ações funcionam no Mac com arquivos reais.
- [ ] Visual igual: pixels nítidos, mesma fonte, ícones e paleta.
- [ ] Roda do Shift segue todas as regras acima, testada pelo dono no Finder.
- [ ] Mini barra segue o mouse sem bloquear cliques.
- [ ] `Treco.app` abre pelo Finder, fora da pasta do projeto.
- [ ] Versão de Windows continua funcionando com o mesmo código.

## Idioma (português e inglês)

- O código e os textos continuam em português. Na hora de desenhar, `core/i18n.py` troca pelo inglês usando `core/en.json` (português → inglês; `{}` marca a parte que muda, como um número ou nome de arquivo).
- O Treco segue o idioma do sistema; no Mac dá para trocar no menu Treco (Português / English), e a troca vale na hora. `TRECO_LANG=en` ou `pt` força um idioma.
- Texto novo na tela: acrescente a linha em `en.json`. Para achar o que ficou sem tradução, rode com `TRECO_I18N_DEBUG=1` e veja `i18n.misses`.
- Nomes dos arquivos gerados também mudam ("foto comprimido.jpg" → "foto compressed.jpg"), e o Resumir página escreve em inglês.
