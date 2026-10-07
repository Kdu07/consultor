# Confiabilidade dos extratos — playbook de reparo de produção

O que o deploy desta fase muda: o parser v3 lê as abas Fundos/CriptoAtivos, limpa os
tickers decorados com `*` e o validador de invariantes passa a **bloquear** gravação com
divergência acima de R$ 1,00 (até R$ 1,00 vira aviso; centavos são arredondamento do
próprio BTG). O banco de produção, porém, ainda carrega as sequelas dos imports antigos:
posições duplicadas/desativadas por chave decorada (`B3:BBAS3*`) e payloads arquivados
pelo parser v1/v2, sem validação.

Este documento é o passo a passo que o dono executa UMA vez, logo após o deploy.
Nenhum código novo é necessário — o reparo usa os fluxos normais do app.

## Passo A — reenviar pelo CHAT o XLSX mais recente

1. Baixar no app BTG o extrato mensal mais recente (o mesmo mês que a carteira reflete,
   ou mais novo) e enviá-lo pelo botão **Importar extrato BTG** do chat.
2. Conferir o preview (agora com o bloco de validação) e confirmar com "sim".

Por que isso conserta: o parser v3 entrega as chaves LIMPAS (`B3:BBAS3`). No upsert,
cada chave limpa reativa a linha original inativa (ou atualiza a ativa), e a
reconciliação desativa as linhas decoradas, que não aparecem mais no lote. Resultado:
nenhum ticker com `*` ativo, yfinance e casamento de proventos voltam a funcionar.

**O chat vem PRIMEIRO, antes do lote.** O lote compara o mês do corte com as posições
atuais da carteira; enquanto a carteira estiver com as chaves decoradas, o reenvio desse
mês pelo lote acusaria `diverge_da_carteira`. Depois do passo A a carteira está limpa e
a comparação volta a fechar.

## Passo B — reenviar os meses antigos pelo LOTE

1. Abrir **Histórico › Extratos** e enviar pelo lote os XLSX dos meses anteriores
   (o BTG deixa baixar mês a mês; até 24 arquivos por lote).
2. Marcar os meses e confirmar. Cada mês **substitui o payload arquivado no lugar**
   (`substitui`), agora com parser v3 + validação — o detalhe do mês passa a mostrar a
   conferência das invariantes, e o encadeamento (V7) dos meses seguintes passa a ser
   avaliado de verdade.

Notas:
- Item com veredito **erro** vem desmarcado e bloqueado — confira o arquivo no app BTG
  e baixe de novo; se o próprio BTG estiver divergente, investigar antes de arquivar.
- Item com **aviso** vem desmarcado mas selecionável: os avisos conhecidos do BTG
  (centavos no razão, Saldo Anterior ± centavos) são esperados e não impedem arquivar.
- O mês do corte reenviado pelo lote aparece como `reenvio_do_atual` depois do passo A;
  se aparecer `diverge_da_carteira`, o passo A não foi concluído.

## Passo C (opcional) — limpar as linhas inativas decoradas

O passo A desativa as linhas decoradas, mas elas continuam no banco (inativas). Para
removê-las de vez:

```bash
fly ssh console -a consultor
python scripts/limpar_posicoes_decoradas.py            # só relata
python scripts/limpar_posicoes_decoradas.py --apagar   # apaga as INATIVAS decoradas
```

O script nunca toca em posição ativa: se relatar alguma decorada ATIVA, volte ao passo A.

## Verificação final

- **Dashboard**: a linha "saldo líquido do extrato" bate com o app BTG.
- **Histórico › Extratos**: nenhum mês com ícone de erro de validação; meses antigos sem
  o selo "anterior ao validador".
- **Desempenho**: sem pendência de quebra de continuidade entre meses consecutivos.
- **Carteira**: nenhum ticker com `*` (o script do passo C relata zero decoradas).
