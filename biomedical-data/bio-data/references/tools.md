# bio-data tool reference

Full per-tool reference for the 14 `mcp__bio-data__*` tools. Read on demand
when the SKILL.md catalog table isn't enough. Tool names, params, and return
shapes mirror `scripts/server.py` + `scripts/apis/*.py` exactly.

## `search_pubmed(query, retmax=20)`

NCBI ESearch on PubMed.

- **Params:** `query` (str, PubMed query syntax, e.g. `BRCA1 AND breast cancer`), `retmax` (int, max PMIDs, default 20).
- **Returns:** `{"pmids": [str...], "count": int}` — `pmids` are the top matches; `count` is the total hit count from NCBI.
- **Example:** `search_pubmed(query="BRCA1", retmax=5)` → `{"pmids": ["11331586", ...], "count": 15987}`

## `fetch_pubmed(pmids)`

NCBI ESummary — summary metadata for PMIDs.

- **Params:** `pmids` (list[str]).
- **Returns:** `{"articles": [{uid, title, ...summary fields}]}` — one dict per PMID with NCBI summary fields (title, authors, source, pubdate, …).
- **Example:** `fetch_pubmed(pmids=["11331586"])`

## `find_related_articles(pmid)`

NCBI ELink — related articles for a PMID.

- **Params:** `pmid` (str).
- **Returns:** `{"related_pmids": [str...]}`.
- **Example:** `find_related_articles(pmid="11331586")`

## `fetch_pmc_fulltext(pmc_ids)`

Europe PMC full-text XML for PMC IDs.

- **Params:** `pmc_ids` (list[str], form `PMC123` or `123`).
- **Returns:** `{"PMC123": "<xml...>"}` — per-ID value is the full-text XML string, or `null` when no full text is available (404).
- **Example:** `fetch_pmc_fulltext(pmc_ids=["PMC231193"])`

## `fetch_clinvar_variant(accession)`

ClinVar clinical interpretation via NCBI E-utilities (db=clinvar). The VCV
prefix is stripped internally — esummary takes the bare numeric variation ID.

- **Params:** `accession` (str, e.g. `VCV000045595` or `45595`).
- **Returns:** `{"accession", "found": bool, "title", "germline_classification", "uid"}` — `germline_classification` is ClinVar's current field (values like `Pathogenic`); `found: false` when the accession has no record.
- **Example:** `fetch_clinvar_variant(accession="VCV000045595")` → `{"accession": "VCV000045595", "found": true, "title": "NM_014000.3(VCL):c.2388G>A (p.Pro796=)", "germline_classification": "Pathogenic", "uid": "45595"}`

## `search_dbsnp_region(chrom, start, stop, assembly, max_rsids=200)`

dbSNP rsIDs in a genomic region (NCBI E-utilities, db=snp).

- **Params:** `chrom` (str `1`–`22`/`X`/`Y`/`MT`), `start`/`stop` (int, 1-based inclusive; keep windows small — dense regions hold thousands of rsIDs/kb), `assembly` (`GRCh38` default / `GRCh37`), `max_rsids` (1–1000, default 200).
- **Returns:** `{"rsids": [str...], "count": int}` — `rsids` is a prefix in Entrez default order; check `count > len(rsids)` for truncation.
- **Example:** `search_dbsnp_region(chrom="1", start=10000, stop=20000)`

## `dbsnp_get_rsids(rsids)`

Full dbSNP records for a batch of rsIDs (NCBI E-utilities, db=snp).

- **Params:** `rsids` (list[str], form `rs123`; ≤ ~20 at a time recommended).
- **Returns:** `{"records": [ {...dbSNP summary...} ]}` — one summary object per rsID.
- **Example:** `dbsnp_get_rsids(rsids=["rs1800722"])`

## `search_gwas_catalog(query, size=20)`

GWAS Catalog associations (EMBL-EBI REST).

- **Params:** `query` (str, free-text — trait, gene, or region terms), `size` (int, default 20).
- **Returns:** `{"associations": [ {...EBI association object...} ], "total": int}` — total is the API's `totalElements`.
- **Example:** `search_gwas_catalog(query="crohn disease")`

## `search_targets(query)`

Open Targets Platform target search (GraphQL).

- **Params:** `query` (str, gene symbol / name).
- **Returns:** `{"hits": [{id (Ensembl ID), name}], "total": int}`.
- **Example:** `search_targets(query="BRAF")` → `{"hits": [{"id": "ENSG00000157764", "name": "BRAF"}], "total": 1}`

## `target_associations(ensembl_id)`

Open Targets genetic-evidence associations for a target (GraphQL).

- **Params:** `ensembl_id` (str, Ensembl gene ID from `search_targets`).
- **Returns:** `{"rows": [{score, disease: {id, name}}]}` — rows sorted by the platform's score.
- **Example:** `target_associations(ensembl_id="ENSG00000157764")`

## `gnomad_variant_frequency(variant)`

gnomAD allele frequencies (public GraphQL API, `gnomad_r4` dataset / GRCh38).

- **Params:** `variant` (str, `chrom-pos-ref-alt` on **GRCh38**, e.g. `7-117559593-ATCT-A`).
- **Returns:** `{"variant", "genome": {ac, an, af}, "exome": {...}}` — per-dataset allele counts/frequencies; empty dicts when the variant isn't found.
- **Example:** `gnomad_variant_frequency(variant="7-117559593-ATCT-A")`

## `query_genes(query, size=10)`

MyGene.info gene query.

- **Params:** `query` (str, Lucene-ish, e.g. `symbol:BRCA1`, `ensembl.gene:ENSG...`, or free text), `size` (int, default 10).
- **Returns:** `{"hits": [{_id, symbol, entrezgene, ensembl, ...}], "total": int}`.
- **Example:** `query_genes(query="symbol:BRCA1")`

## `query_ensembl(path, params="")`

Ensembl REST lookup (polite-pool UA with mailto).

- **Params:** `path` (str, REST path like `lookup/symbol/human/BRCA1`, `variation/human/rs1800722`), `params` (str, optional `key=value&...`, e.g. `expand=1`).
- **Returns:** raw Ensembl JSON.
- **Example:** `query_ensembl(path="lookup/symbol/human/BRCA1", params="expand=1")`

## `query_biomart(xml_query)`

BioMart bulk attribute query (POST XML → TSV).

- **Params:** `xml_query` (str, BioMart XML query; build via the [BioMart web UI](https://www.ensembl.org/biomart/) "XML" export).
- **Returns:** `{"tsv": "..."}` — TSV text, one row per gene/variant, headers in the first line.
- **Example:** batch gene-list → attributes: `{"tsv": "BRCA1\tENSG00000012048\n..."}`
