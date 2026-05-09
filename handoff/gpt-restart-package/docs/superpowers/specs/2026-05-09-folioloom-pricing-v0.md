# FolioLoom Pricing Model v0

Status: test pricing model for the first paid Telegram-bot experiments.
Effective date: 2026-05-09.
Owner: product/business.

This document fixes the first practical pricing model for FolioLoom. It is not
legal advice and does not replace formal payment, tax, consumer-protection, or
copyright review before public production launch.

## Positioning

FolioLoom must not be positioned as a service for unauthorized translation of
commercial books. The first legal target segments are:

- authors and indie authors translating their own manuscripts or books;
- editors and translators working on permitted documents;
- small publishers and rights holders;
- users translating public-domain or otherwise legally permitted texts.

User-facing copy should prefer wording such as `your manuscript`, `authorized
document`, `rights holder`, `editor`, and `public-domain text`. It should avoid
wording such as `translate any book`, `upload any bestseller`, or similar abuse-
enabling claims.

## Recommended Model

Launch with a hybrid model:

- free preview before payment;
- pay-per-document for one-off jobs;
- credits balance for repeat users;
- Telegram Stars as the first Telegram-native purchase mechanism;
- no unlimited subscription during the first paid month.

The default user-facing quality mode should be `Balanced`. `Draft` exists for
price-sensitive tests, while `Careful` is positioned for manuscripts, rights-
holder review, and terminology-sensitive documents.

## Pricing Models Considered

| Model | Buyer | Paid unit | Need frequency | Telegram fit | Main risks | MVP verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Pay-per-document | Authors, editors, publishers | A chapter, manuscript, book, or document | Occasional to project-based | High | Refunds for quality, support load, style retries | Launch first |
| Credits / balance | Repeat authors, editors, small publishers | Prepaid translation balance | Repeat project work | High | Balance accounting, refund complexity, unused credits | Launch with pay-per-document |
| Telegram Stars micro-purchases | Casual users and small jobs | Preview extension, short chapter, small top-up | Ad hoc | High | Low-ticket support economics, platform friction | Use only above a practical minimum |
| Subscription | Translators, power users, publishers | Monthly word allowance or priority | Recurring | Medium | Abuse, unpredictable COGS, piracy expectations | Do not launch in month 1 |
| Hybrid | All legal segments | Document jobs plus credits, later subscriptions | Mixed | High | More UX complexity | Recommended v0 |

## Price Table

List prices are in USD-equivalent value. Telegram invoices should convert them
to Stars at the then-current effective Stars economics and payment-channel
requirements. Store the exact converted Stars amount and pricing version in the
order snapshot.

| Document size | Draft, 1 pass | Balanced, 2 passes | Careful, 3 passes | First-month test price |
| --- | ---: | ---: | ---: | ---: |
| Free preview | $0 | $0 | $0 | 800-1,200 words |
| Short document / chapter up to 10k words | $4 | $7 | $14 | $3 / $5 / $9 |
| Book up to 25k words | $8 | $15 | $29 | $6 / $10 / $20 |
| Book up to 50k words | $14 | $25 | $49 | $10 / $17 / $34 |
| Book up to 100k words | $20 | $39 | $79 | $15 / $27 / $55 |
| Book up to 200k words | $36 | $69 | $139 | $27 / $49 / $99 |
| Extra 100k words | $18 | $35 | $70 | $14 / $25 / $50 |

Minimum paid job price: $3 equivalent. Anything below this should remain free,
preview-only, or bundled into credits because support and refund handling can
exceed the gross profit of very small invoices.

## Credit Packs

Credits are a prepaid FolioLoom balance, not cash. Initial definition:
`1 credit = $1 list-price value`.

| Pack | Price | Bonus | Initial audience |
| --- | ---: | ---: | --- |
| Starter | $10 | 0% | Short documents and cautious first users |
| Author | $25 | 12% | Indie authors |
| Studio | $50 | 20% | Editors and translators |
| Publisher | $100 | 30% | Small publishers and repeat rights holders |

Credits must be auditable in the billing ledger. If a job is refunded, refund
credits before creating cash-equivalent refund support flows.

## Unit Economics Assumptions

The prototype token formula remains useful for internal cost estimation:

- input tokens are estimated from characters plus fragment overhead;
- expected output tokens = input tokens * 1.2;
- estimated LLM cost = input_tokens * $0.28 / 1M + output_tokens * $0.42 / 1M.

Pricing must not be set as a fixed 3x markup on LLM cost. The first business
model reserves for retries, failed work, support, platform/payment fees, abuse
review, legal risk, and perceived value.

Planning assumptions for v0:

- 1 word ~= 1.5 input tokens including overhead;
- platform/payment reserve: 15%;
- refund reserve: 5%;
- support reserve: $0.50-$3.00 per order depending on size and mode;
- raw LLM cost is usually small relative to support, refunds, and payment
  overhead;
- prices below roughly $6 for 25k Balanced, $10 for 50k Balanced, or $18-$20
  for 100k Draft/Balanced start to leave too little room for support and
  refunds.

| Product | Price | Estimated LLM cost | Platform reserve | Refund reserve | Support reserve | Approx. gross margin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 25k Balanced | $15 | $0.08 | $2.25 | $0.75 | $0.50 | 76% |
| 50k Balanced | $25 | $0.15 | $3.75 | $1.25 | $0.75 | 76% |
| 100k Draft | $20 | $0.14 | $3.00 | $1.00 | $1.20 | 73% |
| 100k Balanced | $39 | $0.31 | $5.85 | $1.95 | $1.50 | 75% |
| 100k Careful | $79 | $0.53 | $11.85 | $3.95 | $2.50 | 76% |
| 200k Balanced | $69 | $0.61 | $10.35 | $3.45 | $3.00 | 75% |

Sensitivity rule: moving from 1x to 2x or 3x LLM passes should change price
because it changes perceived quality and latency, but the raw LLM delta alone
does not justify the full price delta. The delta also funds stricter QA,
style retries, support, and lower refund risk.

## Telegram UX Rules

Before payment, show:

- file name and type;
- detected source language and selected target language;
- approximate word count, not token count;
- selected quality mode;
- estimated time range;
- whether partial results are included;
- price in Stars or credits;
- rights/permission confirmation.

Do not show token math to users by default. The bot can say:

`This is about 98k words. Balanced translation includes two quality passes,
chapter-aware processing, progress tracking, and partial results if you cancel.`

Free preview flow:

1. User uploads a file.
2. Bot analyzes file type, language, word count, and metadata.
3. Bot asks the user to confirm they own the text, have permission, or the text
   is public domain / legally permitted.
4. Bot returns a free preview of about 800-1,200 words.
5. Bot shows price options for Draft, Balanced, and Careful.
6. User pays with Stars or credits.
7. Bot shows progress, cancellation, and final/partial result delivery.

## Refund Policy

| Situation | Policy |
| --- | --- |
| Technical failure with no usable output | Full refund in credits or Stars where supported |
| Technical failure with partial usable output | Refund unused portion or rerun at no extra charge |
| User cancellation | Keep completed partial output and charge pro-rata with a $3 minimum |
| Poor quality complaint | One free style/quality retry for Balanced and Careful; discounted retry for Draft |
| Different style request | Included once for Careful; paid retry for Draft and Balanced |
| Duplicate payment | Full refund of duplicate charge |
| Copyright or abuse concern before processing | Cancel and refund |
| Copyright or abuse concern after processing starts | Stop the job, refund unused portion at discretion, and optionally limit the account |

Refund decisions must be auditable and linked to the order, payment event,
translation job, and any support ticket.

## Product Guardrails

Required v0 guardrails:

- explicit rights/permission confirmation before preview or payment;
- unverified users are limited to short documents or 25k words until trust is
  established;
- full-book translation is available only in Author / Rights Holder style copy;
- risky metadata or obvious commercial book metadata should trigger a copyright
  warning and may be preview-only;
- no DRM removal, no paywall bypassing, and no public sharing/library features;
- high-risk repeat behavior can lower limits or require support review;
- medical, legal, financial, and similarly high-stakes documents require a clear
  reminder that AI translation does not replace expert review.

Suggested AUP wording:

`You may only submit content you own, have permission to translate, or are
legally allowed to process. FolioLoom may refuse or limit jobs that appear to
involve unauthorized copyrighted works, DRM circumvention, or mass
redistribution.`

## First-Month Experiment

Launch first-month test prices with about a 30% discount from list prices.

Metrics to track:

- upload to preview conversion;
- preview to payment conversion;
- price acceptance by word tier;
- Draft / Balanced / Careful mix;
- refund rate;
- retry rate;
- support minutes per order;
- gross margin after reserves;
- cancellation point;
- estimate error versus actual token usage;
- abuse flags;
- repeat purchase within 14 days;
- quality rating.

Initial A/B tests:

- Balanced default versus Draft default;
- 800-word preview versus 1,500-word preview;
- document-size tier pricing versus per-100k-word framing;
- rights confirmation before upload versus before payment;
- credits bonus 10% versus 20%.

Raise prices when at least 50 paid jobs show refund rate below 7%, support below
8 minutes per order, stable paid conversion, and average user quality rating of
at least 4 out of 5. First remove the launch discount, then consider a 15%-25%
increase on Careful if demand remains healthy.

Do not launch in month 1:

- unlimited subscriptions;
- "full book for $5" pricing;
- public sharing or community libraries;
- full-book translation for unverified users;
- API access;
- team seats.
