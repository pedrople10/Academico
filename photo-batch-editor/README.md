# Photo Batch Editor

App web para editar varias fotos de uma vez, combinando:

- **Ajuste automatico**: cada foto e analisada individualmente (exposicao, contraste, balanco de branco, saturacao) e recebe uma correcao calculada a partir dos seus proprios pixels — nao e um filtro fixo igual para todas.
- **Prompt de texto**: descreva o que as fotos precisam (ex.: `"mais quente e com mais contraste"`, `"preto e branco cinematic"`, `"vintage"`) e o app soma esse ajuste ao baseline automatico. O interpretador e baseado em regras de palavras-chave (PT-BR e EN), 100% offline — nao depende de nenhuma API de IA paga.
- **Exportacao para Lightroom Classic**: alem das fotos ja editadas em JPEG, o app gera um `.xmp` sidecar por foto (para aplicar os ajustes de forma nao destrutiva direto nos arquivos originais) e uma predefinicao de revelacao `.xmp` com a media dos ajustes do lote.

## Como rodar

```bash
cd photo-batch-editor
npm install
npm start
```

Acesse `http://localhost:3000`. Requer Node.js 18.17 ou mais novo.

Variaveis de ambiente opcionais:

| Variavel | Padrao | O que faz |
| --- | --- | --- |
| `PORT` | `3000` | Porta HTTP |
| `MAX_FILES` | `300` | Maximo de fotos por lote |
| `MAX_FILE_SIZE_MB` | `30` | Tamanho maximo de cada foto |

## Publicar no Render

O arquivo [`render.yaml`](../render.yaml) na raiz do repositorio ja descreve o servico.

1. Entre em [dashboard.render.com](https://dashboard.render.com) com a conta do GitHub.
2. Clique em **New + > Blueprint** e escolha o repositorio `Academico`.
3. Confirme o servico `photo-batch-editor` e clique em **Apply**. O Render roda `npm ci` e `npm start` dentro de `photo-batch-editor/`.
4. Quando o deploy terminar, o app fica em `https://photo-batch-editor-XXXX.onrender.com` (o link aparece no topo da pagina do servico).

Cada push na branch padrao publica de novo automaticamente.

Sem Blueprint (manual): **New + > Web Service**, escolha o repositorio e preencha *Root Directory* `photo-batch-editor`, *Build Command* `npm ci`, *Start Command* `npm start`, *Health Check Path* `/healthz`.

Observacoes do plano gratuito:
- O servico "dorme" depois de 15 min sem acesso; o primeiro acesso depois disso leva uns 50 segundos.
- Sao 512MB de RAM, por isso o `render.yaml` limita o lote a 100 fotos de ate 25MB. As fotos sao processadas uma por vez e gravadas em disco temporario, nao na memoria.
- O disco e temporario: o .zip fica disponivel por 30 minutos ou ate o servico reiniciar.

## Como usar

1. Arraste ou selecione varias fotos.
2. (Opcional) escreva um prompt do que as fotos precisam, ou use os atalhos sugeridos.
3. Ajuste a intensidade da correcao automatica (0% = so o prompt, 100% = automatico normal, 150% = mais forte).
4. Clique em **Processar fotos** e veja o antes/depois de cada uma.
5. Clique em **Baixar tudo (.zip)** para obter:
   - `editado/` — fotos finais em JPEG.
   - `xmp-para-originais/` — um `.xmp` por foto, com o mesmo nome-base do arquivo original, para copiar ao lado dos originais e usar **Metadados > Ler Configuracoes de Metadados** no Lightroom Classic.
   - `preset-lightroom/` — uma predefinicao de revelacao `.xmp` (media do lote) para importar em **Revelar > Predefinicoes > "+" > Importar Predefinicoes**.
   - `LEIA-ME.txt` — essas instrucoes.

## Arquitetura

```
src/
  adjustments/
    types.js              # tipo AdjustmentSet + clamps
    autoAnalyzer.js        # analise automatica por foto (stats do sharp)
    promptInterpreter.js   # regras de palavras-chave -> deltas
    merge.js                # combina automatico (com intensidade) + prompt
  imageProcessor.js        # aplica o AdjustmentSet na foto via sharp
  xmpExporter.js            # gera XMP sidecar e preset de revelacao Lightroom
  sessionStore.js           # pasta temporaria por lote (TTL 30min) para o download do zip
  server.js                  # rotas Express: POST /api/process, GET /api/download/:id, GET /healthz
public/
  index.html, styles.css, app.js   # interface (upload, prompt, preview, download)
```

Nenhuma chave de API externa e necessaria — todo o processamento roda localmente com [`sharp`](https://sharp.pixelplumbing.com/).

## Limitacoes conhecidas

- O motor automatico e heuristico (metodo "gray world" para balanco de branco, desvio padrao para contraste), nao colorimetricamente exato.
- O interpretador de prompt reconhece um conjunto fixo de expressoes comuns em PT-BR/EN; frases muito fora desse vocabulario nao vao gerar ajuste (o app avisa quando nenhum termo foi reconhecido).
- Formatos aceitos: JPEG, PNG, WebP e TIFF. HEIC e RAW nao sao lidos; essas fotos aparecem como "nao foi possivel ler" e o resto do lote segue normalmente.
- Os arquivos `.xmp` sidecar sao pensados para o Lightroom Classic (formato `crs:` da Adobe). Lightroom (cloud/mobile) e outros catalogos podem nao ler esse formato.
