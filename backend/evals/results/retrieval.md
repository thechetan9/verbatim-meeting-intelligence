# Retrieval eval (24 questions, k=6, embeddings=BAAI/bge-small-en-v1.5)

| mode | hit@1 | hit@3 | hit@k | MRR | hit@k attribution | hit@k cross_meeting | hit@k exact | hit@k paraphrase |
|---|---|---|---|---|---|---|---|---|
| lexical | 0.62 | 0.96 | 1.00 | 0.788 | 3/3 | 4/4 | 7/7 | 10/10 |
| dense | 0.50 | 0.92 | 1.00 | 0.712 | 3/3 | 4/4 | 7/7 | 10/10 |
| hybrid | 0.75 | 0.96 | 1.00 | 0.858 | 3/3 | 4/4 | 7/7 | 10/10 |
