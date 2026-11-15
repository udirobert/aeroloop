# X post — OpenServ Hackathon 2 (post manually, then paste the link into the form)

## Main post

> Built an independent auditor for air-quality data with @OpenServAI SERV Reasoning.
>
> It corrects modelled PM2.5 against a real London reference monitor, then proves
> every correction on a holdout it never tuned on. Rejected ideas stay in the record.
>
> 192 ratified hours, LAQN North Kensington: holdout MAE 23.27 → 20.23 µg/m³.
>
> 🧵

## Reply 1 — the SERV finding

> We entered two SERV tiers into the same tournament, byte-identical prompt, same
> holdout windows.
>
> serv-nano: MAE 2.938, $0.000971
> serv-ultra: MAE 2.939, $0.020917
>
> 21.5× the cost for ΔMAE 0.001. The gate shipped nothing and kept the attempt as a
> ghost. Small tier wins on this task.

## Reply 2 — the honesty finding

> SERV also refused our benign scientific prompt twice: finish_reason=content_filter,
> "I can't share that." — still billed.
>
> We did not disable the filter. We record the refusal, the response id and the cost
> in the audit trail. An auditor that hides its own tool's failures is not an auditor.

## Reply 3 — the link

> Code, demo video and the full evidence JSON:
> https://github.com/udirobert/aeroloop
>
> OpenServ Hackathon 2, Open Track. #OpenServ #SERVReasoning

---

Notes before posting:
- Replace `@OpenServAI` with their actual handle if different (check openserv.ai footer).
- Attach `docs/aeroloop-openserv-demo.mp4` to the main post if under X's size limit;
  otherwise attach a 10 s trimmed clip and link the repo for the full video.
- Paste the main post's URL into the submission form's X-post field.