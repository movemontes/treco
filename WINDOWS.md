# Treco: montar a versão de Windows

Guia para o Claude Code no notebook com Windows. O Treco nasceu no Windows e foi levado ao Mac. Desde então ganhou muita coisa, e a maior parte foi testada só no Mac. O código é o mesmo para os dois sistemas.

## Regras (as mesmas do MAC_PORT.md)

1. Fale em português simples: o dono não é programador. Use pronomes neutros.
2. **Nunca simule cliques ou arrastos no mouse real do usuário.** No Windows, um teste assim já deixou o botão do mouse preso.
3. Diga claramente o que foi testado de verdade e o que depende de um teste manual.
4. Não quebre o Mac: o que for só do Windows fica atrás de `WINDOWS` (`core/paths.py`) ou em `ui/winapi.py`.
5. Nunca apague nem mova os originais da pessoa. O que for apagado vai para a Lixeira.
6. Peça antes de publicar qualquer coisa (push, release, site).

## Preparar o notebook

1. Instale o **Python 3.12** do python.org, marcando "Add python.exe to PATH".
2. Instale o **Git**. Para o instalador, instale também o **Inno Setup 6** (jrsoftware.org).
3. No terminal, dentro da pasta do projeto, rode:
   ```
   py -3.12 -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
4. Ponha o **ffmpeg.exe** e o **ffprobe.exe** em `vendor\bin\`. Eles precisam dos filtros `whisper` (legenda) e `ass`. Confira com:
   ```
   vendor\bin\ffmpeg.exe -hide_banner -filters | findstr "whisper ass"
   ```
   As builds "full" recentes (8.0 ou mais nova) do gyan.dev ou do BtbN costumam trazer os dois. Se a antiga versão de Windows ainda estiver no notebook, o ffmpeg dela também serve.
5. A fonte **Clash Grotesk** não vai no GitHub por causa da licença. Copie os `ClashGrotesk-*.otf` do Mac para `treco_app\ui\fonts\`. Sem ela, o Treco usa a Archivo e funciona igual.

## Testar e montar

- Rodar pelo código: `.venv\Scripts\python treco.py`
- Montar: `.venv\Scripts\python vendor\build_win.py`. O resultado sai em `dist\Treco\Treco.exe` e `dist\Treco-windows-setup.exe` (nome fixo: o botão "Baixar para Windows" do site aponta para ele na última release).
- A atualização automática procura na release do GitHub um arquivo terminado em `.exe`: suba o instalador nela, ao lado do `Treco-mac.dmg`.

## O que conferir no Windows (feito depois do Mac, nunca testado lá)

- [ ] O app abre, com o visual novo, o Disquetinho e o ícone novo (o `treco.ico` da raiz é o antigo; o build gera o novo a partir de `icons.app_icon`).
- [ ] Bandeja (`ui/tray.py`), iniciar com o Windows e instância única.
- [ ] Roda do Shift no Explorer, com o tamanho novo (raios 26/70/72/112) e a primeira volta que só mostra o possível.
- [ ] Barra de progresso que segue o mouse, agora com o Disquetinho (`ui/pill.py`: pensando enquanto trabalha, comemorando no fim).
- [ ] Janelas de ferramenta "presas" ao Treco (`ToolDialog.hold_app`: `transient` + `grab_set`), sem sumir quando troca de app.
- [ ] Ferramentas novas da 1.3: BPM e tom, cortar silêncios, limpar voz, organizar páginas do PDF, tarjar, assinar PDF (com certificado .pfx/.p12 pelo pyHanko) e pasta mágica.
- [ ] Inglês: troca de idioma e o `core/en.json`.
- [ ] Legenda com o whisper do ffmpeg do Windows.
- [ ] Converter documentos para PDF (`modules/documents.py` usa o Microsoft Edge).

## Utilidades no Windows

O que é só do Windows fica em `modules/win_utils.py` (mesmos nomes de função do `mac_utils.py`) e em `ui/win_picker.py`.
- **Lixeira**: `cleanup.to_trash` usa `SHFileOperation` com `FOF_ALLOWUNDO`. Nunca apaga de vez.
- **PC acordado**: `SetThreadExecutionState`. **Bateria**: `GetSystemPowerStatus` + `powercfg /batteryreport /xml`.
- **Teste de internet**: baixa e envia dados de teste da Cloudflare (`speed.cloudflare.com`) por uns 10 s cada.
- **Wi-Fi**: `netsh wlan` (a saída vem no idioma do Windows). **Liberar arquivo**: apaga o `:Zone.Identifier`.
- **Histórico de cópias**: `GetClipboardSequenceNumber` e pywin32; respeita os formatos que gerenciadores de senha usam.
- **Desinstalar programa**: lista o registro de "Adicionar ou remover programas" e abre o desinstalador do próprio programa.
- **Conta-gotas**: foto da tela por cima de tudo, com lupa; clique pega a cor, Esc cancela.
- Os textos escritos para o Mac ("Lixo", "Mac", "⌘", "Finder") viram "Lixeira", "PC", "Ctrl+" e "Explorador de Arquivos" em `core/i18n.py` (`WIN_TEXT` e `_WIN_WORDS`), só em textos do próprio Treco.

Ficam só no Mac: **Resumir página** (usa a IA do macOS) e **Captura com rolagem** (precisaria rolar outro programa sozinho, o que a regra 2 proíbe).
