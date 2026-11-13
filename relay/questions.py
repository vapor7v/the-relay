"""Test questions and evaluation criteria for the frozen 18-question suite.

18 questions:
- 15 answerable from the three arXiv papers (Attention Is All You Need, Moshi, Dynamic Chunking)
- 3 unanswerable / out-of-domain questions (must be strictly refused)

For every question, defines:
- required_claims: list of factual claims, all of which must be present for correctness
- optional_details: supporting factual details
- expected_paper: canonical paper identifier ('attention', 'moshi', 'dynamic_chunking', or None)
- expected_citation: canonical citation string / section where known
- expected_grade: 'correct' or 'refused_correctly'
- explicit_failure_conditions: conditions that strictly disqualify an answer
"""

QUESTIONS = [
    # --- Attention Is All You Need (1706.03762v7) ---
    {
        "id": "q01",
        "question": "How many attention heads does the Transformer base model use?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.5]",
        "expected_section": "Section 3.2.2, Table 3",
        "required_claims": [
            {"claim": "Model uses 8 attention heads", "keywords": ["8", "eight"]},
            {"claim": "Mentions attention heads explicitly", "keywords": ["head"]},
        ],
        "optional_details": ["d_k = d_v = 64", "h = 8", "d_model / h = 64"],
        "explicit_failure_conditions": [
            "Claims a number other than 8 heads for the base model",
            "Cites Moshi or Dynamic Chunking instead of Attention Is All You Need",
        ],
        "notes": "8 attention heads (Section 3.2.2, Table 3)",
    },
    {
        "id": "q02",
        "question": "What is the dimensionality of the model (d_model) in the Transformer base model?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.5]",
        "expected_section": "Section 3.1",
        "required_claims": [
            {"claim": "Dimensionality d_model is 512", "keywords": ["512"]},
        ],
        "optional_details": ["d_ff = 2048", "residual layers of dimension 512"],
        "explicit_failure_conditions": [
            "Claims 1024 without qualification as the base model dimension",
            "Cites wrong paper",
        ],
        "notes": "d_model = 512 (Section 3.1)",
    },
    {
        "id": "q03",
        "question": "What positional encoding scheme does the Transformer use?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.6]",
        "expected_section": "Section 3.5",
        "required_claims": [
            {"claim": "Uses sinusoidal encodings (sine and cosine functions)", "keywords_all": [["sinusoid"], ["sine", "cosine"]]},
        ],
        "optional_details": ["wavelengths forming geometric progression from 2pi to 10000*2pi", "fixed vs learned encodings"],
        "explicit_failure_conditions": [
            "Claims learned embeddings only without mentioning sinusoidal scheme",
            "Cites wrong paper",
        ],
        "notes": "Sinusoidal positional encodings (Section 3.5)",
    },
    {
        "id": "q04",
        "question": "What optimizer and learning rate schedule did they use to train the Transformer?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.7]",
        "expected_section": "Section 5.3",
        "required_claims": [
            {"claim": "Uses Adam optimizer", "keywords": ["adam"]},
            {"claim": "Uses warmup learning rate schedule", "keywords": ["warmup", "warm-up"]},
        ],
        "optional_details": ["beta1 = 0.9", "beta2 = 0.98", "warmup_steps = 4000", "d_model^-0.5"],
        "explicit_failure_conditions": [
            "Mentions Adam but omits warmup schedule",
            "Mentions warmup schedule but omits Adam optimizer",
            "Cites wrong paper",
        ],
        "notes": "Adam optimizer with beta1=0.9, beta2=0.98, warmup_steps=4000 (Section 5.3)",
    },
    {
        "id": "q05",
        "question": "What BLEU score did the Transformer big model achieve on WMT 2014 English-to-German?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.8]",
        "expected_section": "Section 6.1, Table 2",
        "required_claims": [
            {"claim": "Achieved a BLEU score of 28.4", "keywords": ["28.4"]},
        ],
        "optional_details": ["improves by more than 2.0 BLEU", "WMT 2014 EN-DE"],
        "explicit_failure_conditions": [
            "Claims 27.3 as the big model score (27.3 is base model)",
            "Claims wrong BLEU score",
            "Cites wrong paper",
        ],
        "notes": "28.4 BLEU score on EN-DE (Section 6.1, Table 2)",
    },

    # --- Moshi (2410.00037v1) ---
    {
        "id": "q06",
        "question": "What is the audio codec used in Moshi and what bitrate does it operate at?",
        "expected_grade": "correct",
        "expected_paper": "moshi",
        "expected_citation": "[Moshi: a speech-text foundation model for real-time dialogue, p.3]",
        "expected_section": "Section 2 / Section 3",
        "required_claims": [
            {"claim": "Codec is Mimi", "keywords": ["mimi"]},
            {"claim": "Bitrate is 1.1 kbps", "keywords": ["1.1", "1.1 kbps", "1.1kbps"]},
        ],
        "optional_details": ["12.5 Hz frame rate", "neural audio codec", "RVQ"],
        "explicit_failure_conditions": [
            "Mentions Mimi but omits 1.1 kbps bitrate",
            "Mentions bitrate but omits Mimi codec name",
            "Cites wrong paper",
        ],
        "notes": "Mimi neural audio codec at 1.1 kbps",
    },
    {
        "id": "q07",
        "question": "How does Moshi handle full-duplex conversation (simultaneous speaking and listening)?",
        "expected_grade": "correct",
        "expected_paper": "moshi",
        "expected_citation": "[Moshi: a speech-text foundation model for real-time dialogue, p.2]",
        "expected_section": "Section 1 / Section 2",
        "required_claims": [
            {"claim": "Models simultaneous dual/parallel streams or inner monologue", "keywords": ["inner monologue", "parallel", "dual", "stream", "streams"]},
        ],
        "optional_details": ["user and system audio channels modeled concurrently", "time-aligned token interleaved"],
        "explicit_failure_conditions": [
            "Describes traditional half-duplex turn-taking without simultaneous stream processing",
            "Cites wrong paper",
        ],
        "notes": "Inner Monologue / parallel audio stream modeling",
    },
    {
        "id": "q08",
        "question": "What is the theoretical latency of the Moshi system from audio in to audio out?",
        "expected_grade": "correct",
        "expected_paper": "moshi",
        "expected_citation": "[Moshi: a speech-text foundation model for real-time dialogue, p.1]",
        "expected_section": "Abstract / Section 1",
        "required_claims": [
            {"claim": "Theoretical latency around 200ms (or 160ms algorithmic frame)", "keywords": ["200", "160"]},
        ],
        "optional_details": ["160ms frame chunk", "80ms codec latency", "real-time factor"],
        "explicit_failure_conditions": [
            "Claims multi-second latency",
            "Fails to state ~200ms theoretical latency or 160ms algorithmic frame",
            "Cites wrong paper",
        ],
        "notes": "Theoretical latency ~200ms (160ms algorithmic frame size + compute)",
    },
    {
        "id": "q09",
        "question": "What training data was used for the Moshi model?",
        "expected_grade": "correct",
        "expected_paper": "moshi",
        "expected_citation": "[Moshi: a speech-text foundation model for real-time dialogue, p.5]",
        "expected_section": "Section 4",
        "required_claims": [
            {"claim": "Trained on conversational speech (e.g. Fisher dataset)", "keywords": ["fisher", "conversational"]},
            {"claim": "Uses synthetic dialogue/audio data", "keywords": ["synthetic"]},
        ],
        "optional_details": ["multi-stage pre-training", "audiobooks", "Helium text backbone data"],
        "explicit_failure_conditions": [
            "Claims only text data was used",
            "Omits conversational audio or synthetic dialogue dataset",
            "Cites wrong paper",
        ],
        "notes": "Fisher conversational telephone dataset + synthetic dialogue",
    },
    {
        "id": "q10",
        "question": "How many parameters does the Moshi language model backbone have?",
        "expected_grade": "correct",
        "expected_paper": "moshi",
        "expected_citation": "[Moshi: a speech-text foundation model for real-time dialogue, p.4]",
        "expected_section": "Section 3",
        "required_claims": [
            {"claim": "Backbone has 7B parameters (Helium 7B)", "keywords": ["7b", "7 billion", "helium"]},
        ],
        "optional_details": ["Helium-7B architecture", "depth and head dimensions"],
        "explicit_failure_conditions": [
            "Claims a parameter count substantially different from 7B",
            "Cites wrong paper",
        ],
        "notes": "7B parameters (Helium 7B text backbone)",
    },

    # --- Dynamic Chunking (2507.07955v2) ---
    {
        "id": "q11",
        "question": "What problem does dynamic chunking solve compared to fixed-size chunking in sequence models?",
        "expected_grade": "correct",
        "expected_paper": "dynamic_chunking",
        "expected_citation": "[Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.2]",
        "expected_section": "Section 1",
        "required_claims": [
            {"claim": "Addresses rigidity of fixed chunks", "keywords": ["fixed", "rigid", "inflexible"]},
            {"claim": "Enables adaptive/variable-length sequence boundaries", "keywords": ["variable", "boundary", "boundaries", "dynamic", "adaptive"]},
        ],
        "optional_details": ["preserves semantic or phonemic continuity across chunk transitions", "data-dependent chunk sizes"],
        "explicit_failure_conditions": [
            "Fails to contrast fixed windows with dynamic/variable boundaries",
            "Cites wrong paper",
        ],
        "notes": "Learns data-dependent dynamic chunk boundaries rather than rigid fixed windows",
    },
    {
        "id": "q12",
        "question": "What datasets were used to evaluate the dynamic chunking approach?",
        "expected_grade": "correct",
        "expected_paper": "dynamic_chunking",
        "expected_citation": "[Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.6]",
        "expected_section": "Section 4",
        "required_claims": [
            {"claim": "Evaluated on Long Range Arena (LRA) or language modeling benchmarks", "keywords": ["lra", "long range", "pg19", "wikitext", "speech"]},
        ],
        "optional_details": ["ListOps", "Text", "Retrieval", "Image", "Pathfinder"],
        "explicit_failure_conditions": [
            "Cites datasets exclusive to WMT translation or Moshi speech without Dynamic Chunking benchmarks",
            "Cites wrong paper",
        ],
        "notes": "LRA benchmarks, language modeling (e.g. PG19, WikiText), audio datasets",
    },
    {
        "id": "q13",
        "question": "How does the dynamic chunking model decide where to place chunk boundaries?",
        "expected_grade": "correct",
        "expected_paper": "dynamic_chunking",
        "expected_citation": "[Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.3]",
        "expected_section": "Section 3",
        "required_claims": [
            {"claim": "Uses a learned boundary predictor / gating mechanism", "keywords": ["boundary", "predictor", "gate", "threshold", "learned"]},
        ],
        "optional_details": ["differentiable boundary decisions", "cumulative score / halting probability"],
        "explicit_failure_conditions": [
            "Claims fixed rule-based punctuation or static heuristic boundaries",
            "Cites wrong paper",
        ],
        "notes": "Learned boundary predictor / gating mechanism that signals chunk termination",
    },

    # --- Unanswerable / Out-of-Domain questions (MUST REFUSE) ---
    {
        "id": "q14",
        "question": "What is the capital of France?",
        "expected_grade": "refused_correctly",
        "expected_paper": None,
        "expected_citation": None,
        "expected_section": None,
        "required_claims": [],
        "optional_details": [],
        "explicit_failure_conditions": [
            "Provides an answer claiming Paris or factual geographic information",
            "Fabricates a citation from the three research papers",
        ],
        "notes": "General world geography — not present in papers",
    },
    {
        "id": "q15",
        "question": "How does GPT-4 compare to the Transformer in terms of architecture?",
        "expected_grade": "refused_correctly",
        "expected_paper": None,
        "expected_citation": None,
        "expected_section": None,
        "required_claims": [],
        "optional_details": [],
        "explicit_failure_conditions": [
            "Answers the comparison using external pretraining knowledge rather than refusing",
            "Fabricates mentions of GPT-4 in the 2017 Transformer paper",
        ],
        "notes": "GPT-4 is proprietary and not mentioned in any of the three papers",
    },
    {
        "id": "q16",
        "question": "What is the environmental impact of training large language models?",
        "expected_grade": "refused_correctly",
        "expected_paper": None,
        "expected_citation": None,
        "expected_section": None,
        "required_claims": [],
        "optional_details": [],
        "explicit_failure_conditions": [
            "Provides an essay on carbon emissions or environmental costs instead of refusing",
            "Fabricates environmental impact claims attributed to the papers",
        ],
        "notes": "Carbon emissions / environmental cost is out of scope of the three papers",
    },

    # --- Cross-paper / Structural questions ---
    {
        "id": "q17",
        "question": "Do any of the three papers use attention mechanisms, and if so, how do their approaches differ?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.4]",
        "expected_section": "Section 3",
        "required_claims": [
            {"claim": "Identifies attention mechanisms in the papers", "keywords": ["attention", "transformer", "self-attention"]},
            {"claim": "Notes adaptation across papers (e.g., Transformer self-attention, Moshi temporal)", "keywords": ["moshi", "chunking", "speech", "cross-attention", "temporal", "extend", "adapts"]},
        ],
        "optional_details": ["multi-head self-attention", "temporal cross-attention", "hierarchical chunk attention"],
        "explicit_failure_conditions": [
            "Denies attention is used in the papers",
            "Omits mentioning how attention is used or extended",
        ],
        "notes": "Transformer introduces multi-head self-attention; Moshi/Dynamic chunking adapt it",
    },
    {
        "id": "q18",
        "question": "What regularization techniques are used in the Transformer model?",
        "expected_grade": "correct",
        "expected_paper": "attention",
        "expected_citation": "[Attention Is All You Need, p.7]",
        "expected_section": "Section 5.4",
        "required_claims": [
            {"claim": "Uses residual dropout", "keywords": ["dropout"]},
            {"claim": "Uses label smoothing", "keywords": ["label smoothing"]},
        ],
        "optional_details": ["P_drop = 0.1", "epsilon_ls = 0.1", "hurts perplexity but improves BLEU"],
        "explicit_failure_conditions": [
            "Mentions dropout but omits label smoothing",
            "Mentions label smoothing but omits dropout",
            "Cites wrong paper",
        ],
        "notes": "Residual dropout and label smoothing (Section 5.4)",
    },
]
