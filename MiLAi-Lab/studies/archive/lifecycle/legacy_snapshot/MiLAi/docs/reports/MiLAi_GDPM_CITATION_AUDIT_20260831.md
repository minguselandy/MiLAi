# Citation Audit Report: MiLAi GDPM Architecture

_Fresh-reviewer audit of the six external sources used by the dual-process Memory architecture proposal, 2026-08-31._

---

## 📋 Summary

| Field | Result |
| --- | --- |
| Audited document | `MiLAi_受治理双过程Memory架构设计_20260831.md` |
| Document SHA-256 | `f5975c57eb81a82ce89c025332de2146163a7970c9c4d7f497db5d75ed74ca5c` |
| Sources | 6 |
| Current-context verdict | 6 KEEP |
| Original statements corrected | 3 |
| Overall verdict | PASS |
| Review independence | same-family |
| Acceptance status | provisional |

Each entry was reviewed in a fresh reviewer thread with web access. The audit checks existence, bibliographic metadata and whether the current architecture sentence is supported. It does not validate MiLAi's engineering claims or experimental results.

## 🔍 Per-source verdicts

### Go-CLS

- **Metadata:** Sun, Advani, Spruston, Saxe and Fitzgerald; _Nature Neuroscience_ 26, 1438–1448 (2023); DOI `10.1038/s41593-023-01382-9`
- **Existence:** verified at the publisher and DOI
- **Context:** KEEP after explicitly describing the result as a theoretical model prediction
- **Boundary:** do not present selective consolidation as an experimentally established universal brain mechanism

### Pattern separation and completion

- **Metadata:** Yassa and Stark; _Trends in Neurosciences_ 34(10), 515–525 (2011); DOI `10.1016/j.tins.2011.06.006`
- **Existence:** verified through PubMed and PMC
- **Context:** KEEP
- **Boundary:** use separation and completion as computational analogies, not exclusive hippocampal operations or software-to-brain equivalences

### NIMH ADHD publication

- **Metadata:** National Institute of Mental Health; NIH Publication No. 24-MH-8300; revised 2024
- **Existence:** verified on the official NIMH site
- **Context:** KEEP with inference labeled
- **Boundary:** NIMH supports persistent impairment, differing presentations, age-related changes, multi-setting symptoms and professional diagnosis. The rule against inferring ADHD from topic switching is a design inference, not a quoted NIMH recommendation

### Mind wandering and inattention symptoms

- **Metadata:** Jonkman, Markus, Franklin and van Dalfsen; _PLOS ONE_ 12(7), e0181213 (2017); DOI `10.1371/journal.pone.0181213`
- **Existence:** verified through PubMed, PMC and PLOS
- **Context:** KEEP after rewrite
- **Correction:** the original broad claim about spontaneous mind wandering impairing sustained task performance was too strong. The current text reports a nonclinical sample, task-unrelated thought, an association with reading comprehension and no corresponding SART performance decrement

### Creativity and ADHD review

- **Metadata:** Hoogman, Stolte, Baas and Kroesbergen; _Neuroscience & Biobehavioral Reviews_ 119, 66–85 (2020); DOI `10.1016/j.neubiorev.2020.09.029`
- **Existence:** verified through ScienceDirect and PubMed
- **Context:** KEEP after rewrite
- **Correction:** the review does not support a blanket creativity advantage. It reports frequent divergent-thinking associations in nonclinical high-trait samples, no consistent clinical advantage and no increased convergent thinking

### Dynamic network switching and creativity

- **Metadata:** Chen et al.; _Communications Biology_ 8, Article 54 (2025); DOI `10.1038/s42003-025-07470-9`
- **Existence:** verified through Nature and PubMed
- **Context:** KEEP after rewrite
- **Correction:** the inverted-U concerns the balance of dwell time in segregated and integrated DMN–ECN states, not switching frequency. Switching frequency itself showed a small positive association with divergent thinking at rest

## 🎯 Final disposition

The six current citations are appropriate for the narrowly worded engineering analogies in the architecture document. None establishes that MiLAi simulates human neurobiology, that ADHD implies creativity, or that topic switching permits clinical inference.

```text
VERDICT: PASS
ACCEPTANCE: PROVISIONAL_SAME_FAMILY
```

## 🔗 Canonical sources

- [Go-CLS publisher record](https://www.nature.com/articles/s41593-023-01382-9)
- [Pattern separation PubMed record](https://pubmed.ncbi.nlm.nih.gov/21788086/)
- [NIMH ADHD publication](https://www.nimh.nih.gov/health/publications/attention-deficit-hyperactivity-disorder-what-you-need-to-know)
- [Mind wandering PubMed record](https://pubmed.ncbi.nlm.nih.gov/28742115/)
- [Creativity and ADHD PubMed record](https://pubmed.ncbi.nlm.nih.gov/33035524/)
- [Dynamic switching publisher record](https://www.nature.com/articles/s42003-025-07470-9)
