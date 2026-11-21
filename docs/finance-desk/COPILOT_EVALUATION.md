# Reckon Copilot evaluation metrics

Local development evaluation on 21 November 2026 using `gpt-6-luna` and the role-scoped `onsumm_db` reporting workflow.

## Results

| Metric | How it is scored | Observed result |
| --- | --- | --- |
| Automatic reply language | One model-generated answer per public prompt. The response must contain an expected script or language marker. | 6 of 6 live prompts passed. |
| Financial retrieval and citations | Compare vendor and inventory counts with independent SQL. Verify cited overdue bills and supplier graph edges against source records. Each question must pass all of its assertions. | 4 of 4 questions passed in the preceding SQL evaluation. |
| Aggregate accuracy | Compare the grouped payables balance and inventory quantity with independent SQL using the same tenant and scope. | All 2 currency groups and all 7 inventory unit groups matched in the preceding SQL evaluation. |
| Live model answer correctness | Ask how many vendors have payment terms of at least 30 days. Check the count in the model response against an independent query. | The first answer and an identical repeat matched. Only the aggregate was supplied as financial evidence. |
| Response latency | Measure a complete service call for the vendor-terms question, including fresh data retrieval and access verification. | 14.62 s on the first call and 4.28 s on the repeat in the preceding SQL evaluation. |
| Regression coverage | Run the focused model-client, chat, approval, SQL and UI suites. | 59 backend and 3 UI tests passed in this change. |

## Language cases

| Input | Expected reply |
| --- | --- |
| “What is working capital? Explain in one sentence.” | English |
| “कार्यशील पूंजी क्या है? एक वाक्य में समझाइए।” | Hindi in Devanagari |
| “பணப்புழக்கம் என்றால் என்ன? ஒரு வாக்கியத்தில் விளக்கவும்.” | Tamil in Tamil script |
| An English question followed by “¿Qué significa liquidez? Usa una frase.” | Spanish for the new question |
| “Working capital kya hota hai? Ek line mein samjhao.” | Romanized Hindi |
| “Explain cash flow in Spanish in one sentence.” | Spanish as explicitly requested |

The language test uses the production answer prompt and model with an empty workspace evidence set. Script and keyword checks measure language choice. A bilingual reviewer would need to score fluency, accounting terminology and translation quality separately. When the model is unavailable, the local evidence summary currently uses English.

## Reproduce

From the repository root with the backend environment active, substitute a unique authorized workspace user. The language run uses the configured model budget. The financial retrieval run disables model calls and checks real records locally.

```powershell
python scripts/eval_copilot_chat.py --display-name "Your workspace user" --language-only
python scripts/eval_copilot_chat.py --display-name "Your workspace user"
python -m pytest -q tests/test_llm_client.py tests/test_finance_desk_workspace_chat.py tests/test_finance_desk_copilot.py tests/test_copilot_finance_sql.py
```

From `frontend`, run `npm test -- --run src/pages/WorkspaceChat.test.tsx src/pages/CopilotPage.test.tsx` for the UI checks.

## Interpreting the numbers

Keep language choice, factual accuracy, citation validity and response time as separate measures. For each new benchmark, record the model, role, language, whether the reply came from the model or the fallback, and whether the query was a repeat. Compare financial answers against SQL at the same tenant, time, unit and currency. Use the API's `Server-Timing` header to distinguish planning and answer time from retrieval and access verification.

The latency figures are a single cold/repeat pair. Production p50 and p95 latency, language-switch accuracy across longer conversations, and human-rated fluency have not yet been measured.
