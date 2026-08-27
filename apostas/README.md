# Apostas — painel + automação (multi-perfil no Opera)

Duas partes que trabalham juntas:

- **`painel/`** — o site (HTML + Supabase) onde você acompanha banca,
  resultado real, IRPF por CPF, vida pessoal e projeção. Roda em qualquer
  navegador, publicado como site estático (GitHub Pages, Vercel, Netlify).
- **`automacao/`** — os scripts Python que rodam no seu computador, abrem
  links em vários perfis do **Opera** de uma vez e fazem a varredura de
  saldo casa por casa, enviando tudo pro painel.

Comece pelo `painel/README.md` (publica o painel primeiro), depois pelo
`automacao/README.md` (configura os perfis do Opera no seu computador).

## Por que Opera e não AdsPower

Este projeto nasceu a partir de uma versão que usava o **AdsPower**, um
navegador antidetect pago. Aqui a automação foi reescrita para funcionar com
o **Opera**, que já vem com suporte a múltiplos perfis e não custa nada
além do que você já tem instalado. O preço dessa troca:

- **cookies e login separados por perfil** — isso o Opera resolve sozinho,
  e é o suficiente pra não misturar sessão entre contas diferentes;
- **fingerprint (canvas, fontes, WebGL) e IP por perfil** — isso o Opera
  *não* resolve sozinho. Sem um proxy configurado por perfil, todos os
  perfis do Opera saem pela mesma internet de casa, e nenhum deles disfarça
  o navegador.

Se cada perfil corresponde a uma pessoa real com o próprio CPF (o uso
pretendido aqui), isso normalmente já é o que as casas de apostas exigem —
"uma conta por pessoa", não "um dispositivo por casa". Ainda assim, sistemas
antifraude podem notar múltiplas contas saindo do mesmo IP/dispositivo.
Detalhes e como mitigar (proxy por perfil) estão em
`automacao/README.md`.

## Aviso

Os cálculos de imposto do painel são estimativa de planejamento, não
apuração fiscal — confirme com um contador antes de decidir algo com base
neles. Sobre a operação em si: verifique os termos de uso de cada casa de
apostas quanto a múltiplas contas antes de rodar isso em produção.
