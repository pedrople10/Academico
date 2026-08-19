const { clamp } = require('./adjustments/types');

// Converte o AdjustmentSet interno (usado no processamento com sharp) para
// os campos "crs:" que o Lightroom Classic entende em arquivos XMP. Os
// mapeamentos assumem uma foto "As Shot" com balanco de branco em torno de
// 5500K/0 de tint como ponto de partida, ja que o app nao le o WB original
// do arquivo raw.
function toLightroomFields(adjustment) {
  const temperatureKelvin = Math.round(5500 + adjustment.temperature * 20);
  const tint = Math.round(clamp(adjustment.tint, -80, 80));
  const exposure = Number(adjustment.exposureEV.toFixed(2));
  const contrast = Math.round(adjustment.contrast);
  const saturation = Math.round(adjustment.saturation);
  const shadows = Math.round(adjustment.shadows);
  // No Lightroom, valores negativos de Highlights2012 recuperam altas
  // luzes; no nosso AdjustmentSet "highlights" positivo significa
  // "recuperar", entao o sinal e invertido na conversao.
  const highlights = Math.round(-adjustment.highlights);

  return {
    whiteBalance: 'Custom',
    temperatureKelvin: clamp(temperatureKelvin, 2000, 50000),
    tint,
    exposure,
    contrast,
    saturation,
    shadows,
    highlights,
    convertToGrayscale: !!adjustment.grayscale,
  };
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Sidecar .xmp: deve ficar salvo com o MESMO nome-base da foto (ex.:
// foto1.jpg + foto1.xmp) na mesma pasta para o Lightroom Classic detectar
// e oferecer para sincronizar as configuracoes de revelacao.
function buildSidecarXmp(adjustment) {
  const f = toLightroomFields(adjustment);
  return `<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Photo Batch Editor 1.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    crs:Version="15.0"
    crs:ProcessVersion="15.4"
    crs:WhiteBalance="${escapeXml(f.whiteBalance)}"
    crs:Temperature="${f.temperatureKelvin}"
    crs:Tint="${f.tint}"
    crs:Exposure2012="${f.exposure}"
    crs:Contrast2012="${f.contrast}"
    crs:Highlights2012="${f.highlights}"
    crs:Shadows2012="${f.shadows}"
    crs:Saturation="${f.saturation}"
    crs:ConvertToGrayscale="${f.convertToGrayscale ? 'True' : 'False'}"
    crs:HasSettings="True"
    crs:AlreadyApplied="False">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
`;
}

// Preset de revelacao (.xmp) para importar em Lightroom Classic > modulo
// Revelar > Predefinicoes > "+" > Importar Predefinicoes. Representa o
// ajuste medio calculado para o lote inteiro, para reaplicar depois.
function buildDevelopPresetXmp(adjustment, presetName, groupName = 'Photo Batch Editor') {
  const f = toLightroomFields(adjustment);
  const uuid = 'PBE-' + Math.random().toString(16).slice(2) + Date.now().toString(16);

  return `<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Photo Batch Editor 1.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    crs:PresetType="Normal"
    crs:Cluster=""
    crs:UUID="${uuid}"
    crs:SupportsAmount="False"
    crs:SupportsColor="True"
    crs:SupportsMonochrome="True"
    crs:SupportsHighDynamicRange="True"
    crs:SupportsNormalDynamicRange="True"
    crs:SupportsSceneReferred="True"
    crs:SupportsOutputReferred="True"
    crs:CameraModelRestriction=""
    crs:Copyright=""
    crs:ContactInfo=""
    crs:Version="15.0"
    crs:ProcessVersion="15.4"
    crs:WhiteBalance="${escapeXml(f.whiteBalance)}"
    crs:Temperature="${f.temperatureKelvin}"
    crs:Tint="${f.tint}"
    crs:Exposure2012="${f.exposure}"
    crs:Contrast2012="${f.contrast}"
    crs:Highlights2012="${f.highlights}"
    crs:Shadows2012="${f.shadows}"
    crs:Saturation="${f.saturation}"
    crs:ConvertToGrayscale="${f.convertToGrayscale ? 'True' : 'False'}">
    <crs:Name>
     <rdf:Alt>
      <rdf:li xml:lang="x-default">${escapeXml(presetName)}</rdf:li>
     </rdf:Alt>
    </crs:Name>
    <crs:Group>
     <rdf:Alt>
      <rdf:li xml:lang="x-default">${escapeXml(groupName)}</rdf:li>
     </rdf:Alt>
    </crs:Group>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
`;
}

module.exports = { toLightroomFields, buildSidecarXmp, buildDevelopPresetXmp };
