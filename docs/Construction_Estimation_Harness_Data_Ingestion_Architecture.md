# Construction Estimation Harness — Data Ingestion Architecture

**Version:** 0.2 (Draft)
**Date:** June 30, 2026
**Status:** Working Document — Architecture Definition Phase
**Changelog:** v0.2 — Added construction domain gap analysis (Section 13), systems engineering gap analysis (Section 14), expanded pipeline inputs to include RFIs and document completeness assessment, added bid structure modeling, subcontractor scoping considerations, and continuous learning requirements.

---

## 1. Executive Summary

This document defines the data ingestion architecture for an AI-powered construction estimation harness. The harness orchestrates an estimating agent through a structured workflow — from receiving a bid package to producing a complete cost estimate. The data ingestion layer is the foundational component of this system, responsible for transforming chaotic, multi-format bid packages into a structured, queryable knowledge base that the estimating agent can reason over reliably.

The core architectural principle is **"context before drawings"**: all supporting documents (specifications, schedules, legends, abbreviation lists) are parsed and structured before drawing interpretation begins, providing the agent with a rich semantic vocabulary that dramatically reduces the difficulty of visual and geometric interpretation.

**v0.2 Note:** This version incorporates gap analysis from both construction domain and systems engineering perspectives. Sections 13 and 14 formalize known deficiencies and open design requirements that must be resolved before this architecture can support a production system.

---

## 2. Problem Statement

Construction bid packages are heterogeneous collections of documents delivered in inconsistent formats. They include architectural, structural, mechanical, electrical, and civil drawings alongside specifications, schedules, and administrative documents. The information required to estimate any single building element is distributed across multiple documents and disciplines.

Current LLMs achieve approximately 75% accuracy on basic text-based construction estimation questions (CEQuest benchmark, 2025), and this accuracy degrades further when visual interpretation of actual drawings is required. The data ingestion layer exists to close this gap by pre-processing and structuring bid package content so the estimating agent operates on organized, cross-referenced data rather than raw documents.

### 2.1 Key Challenges

- **Format inconsistency:** Bid packages arrive as PDFs (vector and scanned), native CAD files (DWG), BIM models (RVT, IFC), or mixed combinations, with no standardized naming conventions.
- **Information distribution:** Estimating a single element (e.g., an exterior wall) requires cross-referencing plan views, sections, details, schedules, and specification sections across multiple documents and disciplines.
- **Semantic loss in PDFs:** When CAD drawings are exported to PDF, semantic information (e.g., "this is a wall") is flattened into raw geometry (lines, arcs, fills), requiring reconstruction of meaning from primitives.
- **Domain-specific conventions:** Construction drawings rely on graphical conventions (line weights, hatch patterns, symbol standards) and abbreviations that require domain knowledge to interpret correctly.
- **Document incompleteness:** Bid packages are frequently issued at intermediate design stages (50% DD, 90% CD) with missing sheets, undefined details, and placeholder specifications. The pipeline must assess and communicate completeness rather than assume it. *(Added v0.2)*
- **Internal contradictions:** Documents within the same bid package routinely contradict each other — structural dimensions that don't match architectural, spec sections that reference different products than what's shown on drawings, or conflicting notes across disciplines. The pipeline must detect and surface these conflicts rather than silently resolving them. *(Added v0.2)*
- **Evolving project records:** RFI responses, addenda, bulletins, and change orders continuously modify the project scope after initial document issue. The pipeline must treat the project record as mutable and track these modifications as first-class data inputs. *(Added v0.2)*

---

## 3. Architectural Principles

The data ingestion pipeline is guided by the following principles:

1. **Schema on Write:** Structure is imposed during ingestion, not during estimation. The estimating agent receives pre-structured, queryable data — not raw documents.
2. **Context Before Drawings:** Supporting documents (specs, schedules, legends) are parsed first to establish a semantic vocabulary before any drawing interpretation occurs.
3. **Binary-First Extraction:** PDF data is extracted from the binary content stream (exact coordinates, text objects, geometric primitives) before any vision-based interpretation, providing structured hints to downstream AI models.
4. **Complementary Extraction Layers:** Deterministic parsing and AI interpretation are complementary — deterministic methods handle structured and predictable content; AI fills gaps and resolves ambiguities.
5. **Provenance Preservation:** Every extracted data point maintains a traceable link to its source document, page, and spatial region.
6. **Idempotent Ingestion:** Processing the same bid package twice produces identical results. Addenda and revisions are handled through versioning, not overwriting.
7. **Graceful Incompleteness:** The pipeline must operate on incomplete documents without failing. Missing information is flagged and quantified, not treated as a fatal error. The system communicates what it knows, what it doesn't know, and what it needs. *(Added v0.2)*
8. **Contradiction Surfacing:** When the pipeline detects conflicting information across documents, it surfaces the conflict to the operator rather than silently choosing one interpretation. Conflicts are first-class data objects in the knowledge graph. *(Added v0.2)*
9. **Fail Explicitly, Recover Gracefully:** Every pipeline phase has defined failure modes, fallback strategies, and retry logic. No phase fails silently. *(Added v0.2)*

---

## 4. Pipeline Overview

The ingestion pipeline operates in six sequential phases. Each phase produces structured output that feeds into subsequent phases and ultimately populates the project knowledge graph.

```
Phase 1: Intake & Normalization
       ↓
Phase 1.5: Document Completeness Assessment  ← NEW (v0.2)
       ↓
Phase 2: Context Document Parsing (Specs, Legends, Schedules, Abbreviations)
       ↓
Phase 3: Sheet Classification & Metadata Extraction
       ↓
Phase 4: Drawing Extraction (Binary Parse → AI-Assisted Interpretation)
       ↓
Phase 5: Knowledge Graph Assembly & Validation
```

---

## 5. Phase 1 — Intake & Normalization

### 5.1 Purpose

Accept bid packages in any delivery format and normalize them into a consistent internal structure for downstream processing.

### 5.2 Input Sources

- Direct file upload (PDFs, DWG, IFC, RVT)
- Plan room download links (PlanHub, iSqFt, BuildingConnected, etc.)
- Email attachments
- Scanned physical documents
- RFI responses (PDF, email) *(Added v0.2)*
- Addenda and bulletin packages *(Added v0.2)*
- Pre-bid meeting minutes and clarifications *(Added v0.2)*

### 5.3 Processing Steps

1. **File inventory:** Catalog all received files with original names, types, sizes, and checksums.
2. **Format detection:** Identify each file's actual format (PDF vector, PDF scanned/raster, DWG, IFC, RVT, DOCX, image) regardless of file extension.
3. **Native file prioritization:** If native CAD/BIM files are available alongside PDFs of the same content, flag the native files as primary sources. Native files contain structured semantic data that PDFs do not.
4. **Deduplication:** Identify and flag duplicate files (by checksum or content similarity).
5. **Addenda handling:** Detect addenda packages, associate revised sheets with their originals, and maintain version history. Superseded sheets are retained but marked as non-current.
6. **RFI integration:** Ingest RFI responses as document patches. Each RFI is linked to the sheets, spec sections, or elements it modifies. RFI responses can supersede or clarify existing document content. *(Added v0.2)*
7. **Storage:** Raw files are stored in object storage with immutable checksums. Processing never modifies originals.

### 5.4 Output

A normalized file registry containing every document in the bid package with metadata: file type, format classification, version status (current / superseded), document category (drawing, specification, RFI, addendum, administrative), and storage path.

---

## 5.5 Phase 1.5 — Document Completeness Assessment *(Added v0.2)*

### 5.5.1 Purpose

Before any extraction begins, assess the completeness of the received bid package and generate a document completeness report. This enables the estimating agent (and human operators) to understand what information is available, what is missing, and what confidence level the downstream estimate can achieve.

### 5.5.2 Completeness Checks

1. **Design stage detection:** Determine the document's design stage — Schematic Design (SD), Design Development (DD), or Construction Documents (CD) — based on title block notations, stamp status, and level of detail. This determines which estimation approach is appropriate (see Section 13.4).
2. **Discipline coverage:** Check whether the package includes drawings for all expected disciplines (architectural, structural, mechanical, electrical, plumbing, civil). Flag any missing disciplines.
3. **Specification completeness:** Check whether a project manual / specification document is included. If present, check whether all divisions relevant to the project type are populated.
4. **Sheet sequence gaps:** Using the drawing index (if present) or sheet numbering patterns, identify missing sheets (e.g., sheets A2.1 and A2.3 exist but A2.2 is absent).
5. **Schedule presence:** Check for the presence of required schedules — door schedule, window schedule, finish schedule, equipment schedule. Flag any that are missing.
6. **Bid form presence:** Check whether a bid form, schedule of values, or scope summary is included.

### 5.5.3 Output

A **Document Completeness Report** containing:
- Detected design stage (SD / DD / CD)
- Discipline coverage (present / missing / partial)
- Sheet inventory with gap identification
- Specification coverage by CSI division
- Schedule inventory (present / missing)
- Overall completeness score (percentage of expected documents received)
- List of specific missing items
- Recommended estimation approach based on available information

This report is surfaced to the human operator before processing continues. The operator can acknowledge the gaps and proceed, or request additional documents before the pipeline advances.

---

## 6. Phase 2 — Context Document Parsing

### 6.1 Purpose

Extract and structure all non-drawing documents that provide semantic context for drawing interpretation. This phase builds the project vocabulary — the set of materials, elements, abbreviations, and symbols that the estimating agent will encounter in the drawings.

**This phase executes before any drawing parsing begins.**

### 6.2 Document Types & Extraction Methods

#### 6.2.1 Project Specifications (Project Manual)

- **Content:** Material specifications, performance requirements, installation procedures, organized by CSI MasterFormat divisions.
- **Format:** Text-based PDF (typically generated from word processors with embedded text layer).
- **Extraction Method:** Direct text extraction using PDF parsing libraries (PyMuPDF, pdfplumber, pdftotext). No OCR required for most spec documents.
- **Structural Parsing:** Parse the CSI hierarchical structure — Division → Section → Part (General / Products / Execution) → Subsection. Each specification clause is stored with its full hierarchical path (e.g., Division 03 > Section 03 30 00 > Part 2 Products > 2.01 Concrete Mix Design > A. Compressive Strength: 4,000 PSI).
- **Contradiction Detection:** Flag cases where specifications reference conflicting products, standards, or performance requirements across divisions (e.g., Division 07 specifying R-19 insulation while Division 09 energy calculations assume R-21). *(Added v0.2)*
- **Output:** Structured specification data indexed by CSI code, with every product, material, and performance requirement queryable.

#### 6.2.2 Drawing Index / Sheet Index

- **Content:** Table listing every sheet number and its title (e.g., "A1.1 - First Floor Plan").
- **Location:** Typically on the first sheet of the set (G0.01 or similar).
- **Extraction Method:** Table extraction from PDF (pdfplumber or Tabula). Small, bounded table — high reliability.
- **Output:** A complete sheet registry mapping sheet numbers to titles, disciplines, and expected content types. Used to prime sheet classification in Phase 3.

#### 6.2.3 Symbol Legends

- **Content:** Graphical symbols with text labels defining their meaning in the drawing set (e.g., circle with diagonal line = floor drain).
- **Location:** Typically on the first sheet of each discipline.
- **Extraction Method:** Hybrid — binary extraction of isolated symbol geometry paired with adjacent text labels. Each symbol's geometric pattern is captured as a template for matching during drawing extraction.
- **Output:** A symbol lookup table mapping geometric patterns to element types, usable as a template-matching reference during Phase 4.

#### 6.2.4 Abbreviation Lists

- **Content:** Project-specific abbreviation definitions (e.g., GWB = Gypsum Wall Board, CMU = Concrete Masonry Unit).
- **Location:** Typically on general information sheets.
- **Extraction Method:** Text extraction and list parsing. Highly structured, two-column format.
- **Output:** A dictionary mapping abbreviation strings to their full meanings. Used to resolve abbreviations encountered during text extraction from drawings.

#### 6.2.5 Keynote Legends

- **Content:** Numbered keynotes with descriptions (e.g., "5 = Apply waterproof membrane per Section 07 11 00").
- **Location:** On individual sheets or on dedicated keynote sheets.
- **Extraction Method:** Table or list extraction from PDF.
- **Output:** A keynote dictionary mapping keynote numbers to descriptions and associated spec section references.

#### 6.2.6 Schedules (Door, Window, Finish, Equipment)

- **Content:** Tabular data itemizing every instance of an element type with its properties (e.g., Door D101: 3'-0" × 7'-0", solid core wood, 90-min fire rating, hardware set H3).
- **Location:** On architectural drawing sheets, typically sheets A6.x, A7.x, or A8.x.
- **Extraction Method:** Table extraction from PDF vector content using pdfplumber or Tabula. Confidence scoring on extraction quality — flag low-confidence extractions for human review.
- **Output:** Structured records for every scheduled element, with all properties parsed into discrete fields. These records become nodes in the knowledge graph.

#### 6.2.7 Bid Form / Schedule of Values

- **Content:** Itemized list of scope divisions or line items that the estimate must cover.
- **Format:** PDF or spreadsheet.
- **Extraction Method:** Text/table extraction.
- **Output:** A completeness checklist used as a validation gate at the end of the estimation process — every line item on the bid form must have a corresponding estimate line.

#### 6.2.8 Bid Structure Documents *(Added v0.2)*

- **Content:** Alternate definitions, allowance requirements, unit price requests, and phasing requirements.
- **Format:** Typically within the bid form or instructions to bidders.
- **Extraction Method:** Text extraction with structural parsing to identify alternates (add/deduct), allowances (fixed dollar amounts for undefined scope), and unit price items (per-unit rates for potential quantity changes).
- **Output:** A bid structure model defining: Base Bid scope, each Alternate with its add/deduct scope description, each Allowance with its dollar amount and scope, each Unit Price item with its description and unit of measure. This model determines how the final estimate is organized — not as a single lump sum, but as a structured bid with components.

#### 6.2.9 RFI Responses *(Added v0.2)*

- **Content:** Architect/engineer responses to contractor questions, often including sketches, revised details, or scope clarifications.
- **Format:** PDF, email, or plan room correspondence.
- **Extraction Method:** Text extraction, with attachment processing for any revised drawings or sketches included in the response.
- **Output:** Structured RFI records linked to the specific sheets, spec sections, or elements they modify. Each RFI response is treated as a document patch that may override or supplement original document content.

#### 6.2.10 Geotechnical Reports *(Added v0.2)*

- **Content:** Soil conditions, bearing capacity, groundwater levels, recommended foundation types, earthwork considerations.
- **Format:** Text-based PDF with tables and boring logs.
- **Extraction Method:** Text and table extraction. Boring log data parsed into structured records with depth, soil type, and test results.
- **Output:** Structured site condition data used to inform foundation, earthwork, and dewatering estimates. Critical for identifying scope that may not appear on drawings (e.g., rock excavation, soil stabilization).

### 6.3 Phase 2 Validation

After context document parsing, the following checks are performed:

- All CSI divisions referenced in the specs are cataloged.
- The drawing index accounts for all sheets present in the file registry.
- All abbreviations used in schedules resolve against the abbreviation list.
- All keynote references point to valid keynote entries.
- Schedule entries contain all required fields (mark, size, type, material at minimum).
- Cross-document contradiction check: spec references that conflict with schedule data or other spec sections are flagged. *(Added v0.2)*
- Bid structure validation: alternates reference identifiable scope, allowances have defined categories, unit prices have defined units. *(Added v0.2)*

---

## 7. Phase 3 — Sheet Classification & Metadata Extraction

### 7.1 Purpose

Classify every drawing sheet by discipline and type, and extract metadata from title blocks to organize the document set for targeted extraction in Phase 4.

### 7.2 Processing Steps

1. **Title block extraction:** Crop the title block region (spatially predictable — lower-right corner) from each sheet. Extract text objects from the title block at the binary level. For non-standard formats, use a vision language model on the cropped region to extract structured fields.
2. **Field extraction:** Parse title block for: sheet number, sheet title, discipline code, project name, architect/engineer of record, revision number, revision date, scale.
3. **Cross-reference with drawing index:** Match extracted sheet numbers against the Phase 2 drawing index. Flag discrepancies (sheets present in files but missing from index, or vice versa).
4. **Discipline classification:** Classify each sheet by discipline based on sheet number prefix and title:
   - A-series: Architectural
   - S-series: Structural
   - M-series: Mechanical
   - E-series: Electrical
   - P-series: Plumbing
   - C-series: Civil
   - L-series: Landscape
   - G-series: General
5. **Drawing type classification:** Further classify each sheet by drawing type based on title and content analysis: plan view, elevation, section, detail, schedule, diagram, general notes.
6. **Scale extraction:** Extract drawing scale(s) from the title block and/or scale notations on the sheet. A single sheet may contain multiple views at different scales.

### 7.3 Output

An enriched sheet registry where every sheet has: discipline, drawing type, scale(s), revision status, and metadata fields extracted from the title block.

---

## 8. Phase 4 — Drawing Extraction

### 8.1 Purpose

Extract architectural and engineering information from drawing sheets, leveraging the context built in Phases 2 and 3 to guide interpretation.

### 8.2 Dual-Layer Extraction Strategy

Drawing extraction operates in two sequential passes.

#### 8.2.1 Pass 1 — Binary Parsing (Deterministic)

Extract raw data directly from the PDF content stream without rendering to pixels.

**Text extraction:**
- Extract all text objects with exact coordinates, font, size, and rotation.
- Resolve abbreviations against the Phase 2 abbreviation dictionary.
- Classify text objects by type using spatial context and formatting: dimension strings (contain feet/inch notation), room names/numbers (centered in enclosed regions), keynote callouts (numbered, with leader lines), general notes (grouped in note blocks), grid line labels (at sheet margins, typically single letters or numbers).

**Geometric extraction:**
- Extract all path operators: lines (moveTo, lineTo), arcs, curves, rectangles.
- Extract line properties: weight (stroke width), style (solid, dashed, center), color.
- Extract fill regions and hatch patterns.

**Deterministic pattern matching:**
- **Walls:** Pairs of parallel lines within 4"–12" at drawing scale, running more than 2' in length, with or without hatching between them.
- **Dimension strings:** Text objects containing dimensional notation positioned between extension lines.
- **Grid lines:** Long lines spanning the full drawing area with alphanumeric labels at their ends.
- **Section cut markers:** Circle symbols with directional arrows and sheet reference text.
- **Drawing borders and title blocks:** Outermost rectangular borders — excluded from element detection.

**Output:** A structured data layer containing all text objects with positions and classifications, all geometric primitives with properties, and all deterministically identified elements with confidence scores.

#### 8.2.2 Pass 2 — AI-Assisted Interpretation (Contextual)

Provide the binary-extracted data as structured context to an AI model for gap-filling and ambiguity resolution.

**Model input:** The rendered sheet image *plus* the structured data from Pass 1:
- All text objects identified and positioned
- All lines classified as probable walls, grid lines, dimension strings
- Unclassified geometric regions flagged for interpretation
- Relevant context from Phase 2: wall types defined in specs, door types from schedule, symbol definitions from legend

**Model tasks:**
- Classify unidentified geometric patterns (e.g., plumbing fixtures, electrical symbols, custom details)
- Resolve ambiguous element classifications from Pass 1
- Associate text annotations with the drawing elements they describe (e.g., link a keynote callout to the wall it points to)
- Count element instances (e.g., number of occurrences of a specific beam type on a framing plan)
- Cross-reference detail callout bubbles to their destination sheets

**Output:** Enriched element data with AI-classified types, text-to-element associations, and element counts.

### 8.3 Native File Processing (Preferred Path)

When native CAD or BIM files are available, they bypass the dual-layer extraction:

- **IFC files:** Parsed directly using IfcOpenShell. All elements, properties, material assignments, and spatial relationships are available as structured data.
- **RVT files (Revit):** Processed via Revit API or DB Link export. Provides full element data including families, types, parameters, and schedule data.
- **DWG files:** Parsed using ODA/Teigha libraries. Layer information provides partial semantic context (e.g., elements on the "A-WALL" layer are walls), though less rich than BIM data.

Native file data feeds directly into the knowledge graph with high confidence, requiring minimal AI interpretation.

### 8.4 Phase 4 Validation

- Extracted element counts are compared against schedule counts (e.g., number of doors found on plans vs. number of entries in the door schedule).
- Extracted dimensions are sanity-checked against drawing scale (e.g., a residential room dimension should not exceed 40'–50').
- Every element extracted is linked to a source sheet and spatial region (provenance).
- Unclassified regions exceeding a size threshold are flagged for human review.
- Cross-discipline consistency: structural grid matches architectural grid; MEP penetrations align with architectural openings. *(Added v0.2)*

---

## 9. Phase 5 — Knowledge Graph Assembly

### 9.1 Purpose

Assemble all extracted data into a unified knowledge graph (Neo4j) that represents the complete project as a network of interconnected entities.

### 9.2 Node Types

| Node Type | Source Phase | Examples |
|---|---|---|
| Project | Phase 1 | Project name, location, owner, architect |
| Sheet | Phase 3 | Sheet number, title, discipline, type, scale, revision |
| Spec Section | Phase 2 | CSI code, title, content (Part 1/2/3) |
| Element | Phase 4 | Walls, doors, windows, beams, columns, fixtures |
| Material | Phase 2 | Concrete, masonry, gypsum board, insulation |
| Room / Space | Phase 4 | Room name, number, floor level |
| Schedule Entry | Phase 2 | Door D101, Window W3, Finish for Room 201 |
| Symbol Definition | Phase 2 | Symbol pattern, element type, legend source |
| Keynote | Phase 2 | Keynote number, description, spec reference |
| RFI | Phase 2 | RFI number, question, response, affected scope *(Added v0.2)* |
| Alternate | Phase 2 | Alternate number, add/deduct, scope description *(Added v0.2)* |
| Allowance | Phase 2 | Allowance description, dollar amount, scope *(Added v0.2)* |
| Conflict | Phase 2/4 | Conflicting data points, source documents, resolution status *(Added v0.2)* |

### 9.3 Relationship Types

| Relationship | From → To | Example |
|---|---|---|
| APPEARS_ON | Element → Sheet | Wall Type A appears on sheet A1.1 |
| HAS_TYPE | Element → Schedule Entry | Door instance → Door D101 |
| IS_SPECIFIED_IN | Material → Spec Section | Cast-in-place concrete → Section 03 30 00 |
| CONTAINS | Room → Element | Room 201 contains Door D101 |
| LOCATED_IN | Element → Room / Space | Light fixture → Room 201 |
| DETAILED_ON | Element → Sheet | Wall section → Detail on sheet A5.3 |
| REFERENCES | Keynote → Spec Section | Keynote 5 → Section 07 11 00 |
| SUPERSEDES | Sheet → Sheet | Sheet A1.1 Rev 2 → Sheet A1.1 Rev 1 |
| COMPOSED_OF | Element → Material | Wall Type A → Face brick, insulation, studs, GWB |
| MODIFIES | RFI → Element/Sheet/Spec | RFI #12 modifies door schedule on A8.1 *(Added v0.2)* |
| CONFLICTS_WITH | Spec/Element → Spec/Element | Spec 07 insulation vs. Spec 09 R-value *(Added v0.2)* |
| INCLUDED_IN_ALTERNATE | Element → Alternate | Green roof assembly → Alternate #2 *(Added v0.2)* |
| SCOPED_TO | Element → Bid Division | Concrete foundation → Base Bid *(Added v0.2)* |

### 9.4 Graph Validation Queries

The following queries serve as completeness and consistency checks:

- **Missing scope:** Spec sections with no connected elements (materials specified but not found in drawings).
- **Orphaned elements:** Elements found in drawings with no spec section linkage.
- **Schedule mismatches:** Schedule entries not connected to any element instance on the drawings.
- **Incomplete rooms:** Rooms without finish schedule entries.
- **Unlinked details:** Detail callouts on plans that don't connect to a detail sheet.
- **Bid form coverage:** Bid form line items without corresponding estimate entries (post-estimation validation).
- **Unresolved conflicts:** Conflict nodes without a resolution status. *(Added v0.2)*
- **Alternate scope gaps:** Alternates referenced in bid form without linked elements. *(Added v0.2)*
- **RFI coverage:** RFI responses that haven't been linked to affected documents. *(Added v0.2)*

---

## 10. Data Storage Architecture

The knowledge graph does not store all data. It serves as the **relationship and semantic layer** within a multi-store architecture:

| Store | Technology | Content |
|---|---|---|
| Object Store | S3 / MinIO | Raw bid package files (immutable originals) |
| Document Store | Elasticsearch | Extracted text with full-text search (specs, notes, annotations) |
| Structured Store | PostgreSQL | Schedule data, parsed tables, extracted dimensions, element properties |
| Knowledge Graph | Neo4j | Entity nodes, relationships, cross-references between all stores |
| Version Store | Git-based or custom | Revision history for addenda and change tracking |

Each extracted data point in any store maintains a provenance record: source file, source page, spatial region (bounding box coordinates), extraction method, and confidence score.

---

## 11. Validation Philosophy

Validation is not a single step — it is embedded at every phase boundary and within phases. The principle is **"fail early, fail loudly"**: extraction errors caught during ingestion are orders of magnitude cheaper to fix than errors discovered during estimation or, worse, after bid submission.

### 11.1 Validation Gate Summary

| Gate | Location | Checks |
|---|---|---|
| V0 | Post-Phase 1.5 | Document completeness, design stage detection, discipline coverage |
| V1 | Post-Phase 1 | File completeness, format detection accuracy, addenda sequencing |
| V2 | Post-Phase 2 | Spec structure integrity, schedule field completeness, abbreviation coverage, cross-document contradiction detection |
| V3 | Post-Phase 3 | Sheet classification accuracy, drawing index alignment, scale extraction |
| V4 | Post-Phase 4 | Element count vs. schedule count, dimension sanity, provenance completeness, cross-discipline consistency |
| V5 | Post-Phase 5 | Graph connectivity, orphan detection, scope coverage, conflict resolution status |

### 11.2 Confidence Scoring

Every extracted data point carries a confidence score:

- **High (deterministic):** Extracted from binary PDF data or native file with no ambiguity (e.g., text objects, structured table cells, BIM element properties).
- **Medium (pattern-matched):** Identified by deterministic pattern matching on geometric primitives (e.g., parallel lines classified as walls).
- **Low (AI-interpreted):** Classified by AI model from visual or contextual inference (e.g., fixture identification, ambiguous symbol classification).

Data points below configurable confidence thresholds are flagged for human review before the estimating agent uses them.

---

## 12. Domain-Specific Business Rules *(Added v0.2)*

The ingestion pipeline and downstream estimating agent must enforce domain-specific business rules that LLMs do not reliably internalize. These rules are implemented as deterministic checks in the validation layer, not delegated to the AI model.

### 12.1 Quantity Rounding Rules

- Pourable materials (concrete, grout) are always rounded **up** to the next whole unit to ensure sufficient material and account for waste.
- Lumber is ordered in standard lengths (8', 10', 12', 14', 16', 20'). Quantities must be rounded up to the next standard length.
- Sheet goods (plywood, drywall) are counted in full sheets. Partial sheet usage still requires purchasing a full sheet.
- Discrete items (doors, windows, fixtures) are whole numbers — no fractional quantities.

### 12.2 Waste and Coverage Factors

- Standard waste factors apply by material type (e.g., 5–10% for concrete, 10–15% for drywall, 5% for paint).
- Flooring and ceiling materials have coverage losses due to pattern matching and room geometry.
- These factors must be applied after quantity takeoff, not embedded in the takeoff itself, to maintain auditability.

### 12.3 Unit Consistency

- All dimensions must be converted to consistent units before calculation (e.g., inches to feet before computing area in square feet).
- The CEQuest benchmark demonstrated that LLMs frequently fail at unit conversion in construction contexts (e.g., converting 4" to 0.33' for volume calculations).

---

## 13. Construction Domain Gap Analysis *(Added v0.2)*

The following gaps represent areas where the current architecture does not adequately reflect the realities of construction estimation practice. Each gap is categorized by severity and includes a preliminary remediation approach.

### 13.1 Subcontractor Scoping & Bid Leveling

**Gap:** The architecture assumes the general contractor self-performs all trades and produces a detailed takeoff for every scope division. In practice, a GC self-performs only 2–3 trades (typically general conditions, concrete, carpentry) and obtains subcontractor bids for the remaining scope (electrical, mechanical, plumbing, fire protection, roofing, masonry, steel, etc.). A significant portion of the estimating process involves writing scope descriptions for subcontractors, distributing those scopes, receiving sub quotes, and "leveling" competing bids to ensure they cover equivalent scope.

**Impact:** Critical. Without subcontractor scoping, the system cannot produce a realistic GC-level estimate for commercial projects.

**Remediation Approach:** The pipeline must distinguish between self-performed scope (requiring detailed quantity takeoff) and subcontracted scope (requiring scope narrative generation). The knowledge graph should model scope boundaries — which CSI divisions or elements are self-performed vs. subcontracted — and the system should be capable of generating scope description documents from the parsed specs and drawings. Bid leveling requires a separate workflow for ingesting and comparing subcontractor proposals. This is a significant architectural extension.

### 13.2 Means and Methods

**Gap:** The architecture focuses exclusively on the "what" (what materials and elements exist) and ignores the "how" (how the building will be constructed). Estimation requires understanding construction means and methods — formwork types, concrete placement methods (pump vs. direct pour vs. crane and bucket), equipment requirements, crew composition, productivity rates, and sequencing.

**Impact:** High. Quantities without means and methods produce material costs but not labor costs, equipment costs, or realistic schedules.

**Remediation Approach:** The estimating agent (downstream of the ingestion pipeline) must have access to a means-and-methods knowledge base — either through retrieval-augmented generation from a construction methods database, or through a domain-specific model fine-tuned on construction productivity data. The ingestion pipeline should extract any means-and-methods information present in the documents (e.g., spec requirements for concrete placement method, structural notes about erection sequence) and feed it into the knowledge graph. However, much of this knowledge is experiential and company-specific, not document-derived.

### 13.3 Alternates, Allowances, and Unit Prices

**Gap (Partially Addressed):** The bid form section now captures alternates, allowances, and unit prices, but the downstream impact on estimate organization is not fully modeled. Alternates require the estimate to be structured as a Base Bid plus discrete add/deduct packages. Allowances require placeholder line items at specified dollar amounts. Unit prices require per-unit cost breakdowns that may differ from lump-sum pricing.

**Impact:** High. A bid that doesn't match the owner's required bid structure will be rejected regardless of accuracy.

**Remediation Approach:** The bid structure model from Phase 2 must drive estimate organization. The estimating agent must produce output in the format: Base Bid + Alternate 1 (add/deduct) + Alternate 2 (add/deduct) + Allowances + Unit Prices. The knowledge graph must track which elements belong to the Base Bid vs. which alternates.

### 13.4 Estimation Level vs. Design Stage

**Gap:** The architecture assumes a single estimation approach (detailed quantity takeoff from construction documents). In practice, different design stages require different estimation methods:
- **Conceptual / SD:** Cost per square foot based on building type and location, using historical data.
- **Design Development (DD):** Assembly-based estimating using partially defined systems (e.g., "exterior wall assembly" priced per SF rather than individual components).
- **Construction Documents (CD):** Detailed quantity takeoff and unit pricing.

**Impact:** High. Running a CD-level pipeline against SD-level documents will produce garbage — the information simply isn't there for detailed takeoff.

**Remediation Approach:** Phase 1.5 (Document Completeness Assessment) detects the design stage. The pipeline should route to different estimation strategies based on the detected stage. The ingestion pipeline itself may need simplified extraction paths for early-stage documents (e.g., extract building footprint and gross square footage for conceptual estimates rather than individual elements).

### 13.5 General Conditions and Project-Specific Costs

**Gap:** The architecture focuses on direct construction costs (materials and labor for building elements) and ignores general conditions — the overhead costs of running a construction project. These include supervision, temporary facilities (trailers, toilets, fencing), temporary utilities, insurance, permits, equipment mobilization, project management, safety programs, clean-up, and dumpsters.

**Impact:** Medium-High. General conditions typically represent 8–15% of project cost and are a significant component of every estimate.

**Remediation Approach:** General conditions are largely driven by project duration, size, and location rather than by what's in the drawings. The pipeline should extract project duration (from the specs or bid documents), project location, and project size, which the estimating agent can use to generate a general conditions estimate from templates or historical data.

### 13.6 Incomplete Documents and Assumptions

**Gap:** The architecture detects document gaps (Phase 1.5) but doesn't address what happens next. In practice, estimators don't stop when information is missing — they make assumptions, document those assumptions, and include contingency. A bid built on incomplete documents carries a quantified assumption log and a corresponding risk-adjusted markup.

**Impact:** High. A system that refuses to estimate when information is incomplete is unusable in the real world.

**Remediation Approach:** The system must support an assumption management workflow. When the ingestion pipeline or estimating agent encounters a gap, it should generate an assumption record (e.g., "Foundation depth assumed at 4'-0" based on typical conditions — geotechnical report not provided"), link that assumption to the affected estimate line items, and quantify the cost risk if the assumption proves wrong. Assumptions aggregate into a project risk register that informs contingency markup.

---

## 14. Systems Engineering Gap Analysis *(Added v0.2)*

The following gaps represent areas where the current architecture lacks the operational infrastructure required for a production system.

### 14.1 Error Handling and Recovery

**Gap:** The pipeline describes a happy path with no defined failure modes, retry strategies, fallback behaviors, or circuit breakers.

**Impact:** Critical for production. Any phase can fail — PDF parsing libraries crash on malformed files, AI models return unusable output, network calls to cloud APIs timeout.

**Required Design Decisions:**
- **Phase-level failure modes:** For each phase, define what constitutes a recoverable error (retry) vs. a fatal error (halt with notification).
- **Retry strategy:** Exponential backoff with jitter for API calls. Configurable retry count per phase.
- **Circuit breaker pattern:** If a specific extractor fails repeatedly (e.g., table extraction failing on a particular architect's format), circuit-break that extractor and route to the fallback (e.g., AI-based table reading instead of deterministic).
- **Partial completion:** If Phase 4 fails on 3 of 50 sheets, the pipeline should continue and mark those 3 sheets as unprocessed rather than failing the entire job.
- **Dead letter queue:** Failed extraction items go to a review queue for manual processing, not into a black hole.

### 14.2 Human-in-the-Loop Operations

**Gap:** The document says "flag for human review" in multiple places but never defines the operational workflow for human review.

**Impact:** Critical. Without a review workflow, flagged items accumulate with no resolution path.

**Required Design Decisions:**
- **Review interface:** What does the human reviewer see? At minimum: the flagged item, the source document region (with visual highlighting), the system's best guess, and the confidence score.
- **Correction workflow:** How does the reviewer submit corrections? Corrections must flow back into the pipeline and update the structured data and knowledge graph.
- **Synchronous vs. asynchronous:** Does the pipeline block waiting for human review, or continue and backfill when reviews are completed? Likely answer: asynchronous for most items, synchronous only for critical-path blockers.
- **Escalation:** What happens if a flagged item requires expertise the reviewer doesn't have (e.g., a structural detail that needs an engineer's interpretation)?
- **SLA / turnaround:** What's the expected review turnaround time? Bid deadlines create real time pressure — a review queue that takes 3 days to clear is useless for a bid due tomorrow.

### 14.3 Scalability and Performance

**Gap:** No discussion of how the pipeline scales across different project sizes, expected processing times, or cost per bid.

**Impact:** High. Economic viability depends on processing cost relative to the value of the estimate.

**Required Design Decisions:**
- **Project size tiers:** Define expected performance for small (20-sheet TI), medium (100-sheet commercial), and large (500-sheet institutional) projects.
- **Parallelization:** Phases 3 and 4 can operate on individual sheets in parallel. Define the concurrency model.
- **AI model cost:** Vision model API calls are expensive. Estimate the per-sheet cost and the total per-bid cost at each project size tier.
- **Processing time targets:** What's acceptable? For a bid due in 48 hours, how much of that time can the pipeline consume? Target: ingestion complete within 2–4 hours for a 200-sheet set, leaving the estimating agent and human review time to work.
- **Caching:** Common symbols, standard details, and frequently encountered architectural patterns should be cached across projects to avoid redundant AI interpretation.

### 14.4 Observability

**Gap:** No logging, metrics, alerting, or dashboard design. The pipeline is opaque to operators.

**Impact:** High. Estimators waiting on pipeline results need visibility into progress and issues.

**Required Design Decisions:**
- **Progress tracking:** Per-phase progress (e.g., "Phase 4: 37/52 sheets processed") visible to operators in real time.
- **Metrics:** Extraction success rates, confidence score distributions, processing time per phase, human review queue depth, error rates by extractor type.
- **Alerting:** Automated alerts for pipeline failures, unusually low confidence scores, or processing time exceeding thresholds.
- **Audit logging:** Every extraction decision logged with inputs, outputs, method used, and confidence. Supports post-bid review ("why did the system estimate 450 LF of wall instead of 500?").

### 14.5 Testing and Validation Strategy

**Gap:** No strategy for validating that the pipeline itself produces correct output.

**Impact:** Critical. Without a test suite, changes to the pipeline cannot be verified against known-good results.

**Required Design Decisions:**
- **Reference project set:** Assemble 10–20 projects where both the raw bid package and a known-good human estimate exist. These become the test suite.
- **Extraction accuracy metrics:** Define per-phase accuracy measurements (e.g., Phase 3 sheet classification accuracy, Phase 4 element count accuracy vs. human takeoff).
- **Regression testing:** Every pipeline change is run against the reference set. Accuracy must not regress.
- **Domain expert review:** Periodic review of pipeline output by experienced estimators, with findings fed back into the pipeline as bug fixes or rule adjustments.

### 14.6 Data Security and Confidentiality

**Gap:** No discussion of data governance, access controls, or confidentiality requirements for construction documents.

**Impact:** High. Construction documents are confidential and often covered by NDAs.

**Required Design Decisions:**
- **Data residency:** Where are documents stored? Some owners and government projects require data to remain in specific jurisdictions.
- **Cloud AI model privacy:** If using cloud-based vision or language models, documents are transmitted to third-party APIs. Assess data processing agreements with model providers. Consider on-premise model deployment for sensitive projects.
- **Access controls:** Multi-tenant isolation — one client's project data must never be accessible to another client.
- **Retention policies:** How long are project documents and extracted data retained? Construction litigation can occur years after project completion, which may require extended retention, but privacy regulations may require deletion.
- **Encryption:** Data at rest (storage) and in transit (API calls) must be encrypted. Key management strategy required.

### 14.7 Continuous Learning and Feedback Loop

**Gap:** The pipeline is static — it does not improve from corrections or accumulate domain knowledge across projects.

**Impact:** High. Without learning, the system stays at its initial accuracy level permanently.

**Required Design Decisions:**
- **Correction capture:** When a human reviewer corrects a misclassified element, that correction is stored as a labeled training example.
- **Model retraining cadence:** How frequently are AI models retrained or fine-tuned on accumulated corrections? Options: batch (monthly), triggered (when correction count exceeds threshold), or continuous.
- **Cross-project knowledge:** Common elements, standard details, and firm-specific conventions (e.g., "Architect X always uses this title block format") should be learned across projects and applied to new ones.
- **Performance tracking:** Track per-project accuracy trends over time. The system should demonstrably improve with each project processed.
- **Guardrails:** Learning must not introduce regressions. New model versions are validated against the reference project test suite before deployment.

### 14.8 Multi-User Collaboration

**Gap:** The architecture assumes a single operator. Real estimation is collaborative — multiple estimators may work on different scope divisions simultaneously, a chief estimator reviews and assembles the final bid, and project managers may need read access to status and results.

**Impact:** Medium. Single-user mode is viable for MVP but insufficient for production use on large projects.

**Required Design Decisions:**
- **Concurrent access:** Multiple estimators reviewing and correcting pipeline output simultaneously without conflicts.
- **Role-based access:** Different roles (estimator, reviewer, project manager, admin) with different permissions.
- **Audit trail:** Who changed what, when, and why — especially important for bid disputes.

---

## 15. Open Questions & Future Work

1. **Scanned PDF handling:** Pipeline currently optimized for vector PDFs with embedded text. Scanned/raster PDFs require OCR as a preprocessing step, introducing error rates not present in the vector path. Strategy for mixed-format sheets (partially vector, partially raster) needs definition.
2. **Hand-drawn markup interpretation:** Bid packages sometimes include hand-annotated markups on printed sheets. These require specialized handwriting recognition and are currently out of scope.
3. **Multi-building / multi-phase projects:** Large projects with multiple buildings or construction phases need additional organizational layers in the graph. The current schema assumes a single-building project.
4. **Real-time pricing integration:** The ingestion pipeline produces the *what* (elements and quantities). Integration with pricing databases (RSMeans, local supplier pricing, historical cost data) for the *how much* is a downstream concern handled by the estimating agent and is outside the scope of this document.
5. **Feedback loop from estimation:** When the estimating agent encounters data it cannot interpret or finds inconsistencies, it should be able to flag these back to the ingestion pipeline for reprocessing or human review. This feedback mechanism needs design.
6. **Subcontractor bid integration:** Mechanism for ingesting, parsing, and leveling subcontractor proposals against generated scope documents. *(Added v0.2)*
7. **Historical cost database:** Architecture for storing and querying completed project costs to inform future estimates and validate current ones. *(Added v0.2)*
8. **Means and methods knowledge base:** Design of the retrieval system for construction methods, productivity rates, and equipment requirements. *(Added v0.2)*
9. **Assumption management workflow:** Full design of the assumption capture, documentation, and risk quantification system. *(Added v0.2)*
10. **Change order processing:** Post-award, the system should support change order estimation using the same knowledge graph built during the bid phase, with incremental updates rather than full reprocessing. *(Added v0.2)*

---

## Appendix A — Technology Stack (Preliminary)

| Component | Candidate Technologies |
|---|---|
| PDF binary parsing | PyMuPDF (fitz), pdfplumber, pdfminer.six |
| Table extraction | pdfplumber, Tabula, Camelot |
| OCR (scanned PDFs) | Tesseract, EasyOCR, Google Cloud Vision |
| Native CAD parsing | IfcOpenShell (IFC), ODA/Teigha (DWG) |
| BIM data extraction | Revit API, IFC parsing libraries |
| Vision language models | Claude (Anthropic), GPT-4 vision (OpenAI), Gemini (Google) |
| Knowledge graph | Neo4j |
| Full-text search | Elasticsearch / OpenSearch |
| Structured data store | PostgreSQL |
| Object storage | S3 / MinIO |
| Pipeline orchestration | Apache Airflow, Prefect, or custom harness |
| Observability | Prometheus + Grafana (metrics), ELK stack (logging) *(Added v0.2)* |
| Task queue | Celery / Redis, or cloud-native (SQS, Cloud Tasks) *(Added v0.2)* |
| Authentication / RBAC | Keycloak, Auth0, or cloud IAM *(Added v0.2)* |

---

## Appendix B — CSI MasterFormat Divisions (Commonly Estimated)

| Division | Title | Typical Content |
|---|---|---|
| 01 | General Requirements | General conditions, temporary facilities, project management *(Added v0.2)* |
| 02 | Existing Conditions | Demolition, site remediation *(Added v0.2)* |
| 03 | Concrete | Foundations, slabs, structural concrete |
| 04 | Masonry | CMU walls, brick veneer, stone |
| 05 | Metals | Structural steel, misc metals, railings |
| 06 | Wood/Plastics/Composites | Framing, millwork, casework |
| 07 | Thermal & Moisture Protection | Insulation, roofing, waterproofing, sealants |
| 08 | Openings | Doors, windows, hardware, glazing |
| 09 | Finishes | Drywall, paint, flooring, ceiling tile |
| 10 | Specialties | Toilet accessories, signage, lockers *(Added v0.2)* |
| 11 | Equipment | Kitchen equipment, lab equipment *(Added v0.2)* |
| 12 | Furnishings | Furniture, window treatments *(Added v0.2)* |
| 14 | Conveying Equipment | Elevators, escalators *(Added v0.2)* |
| 21 | Fire Suppression | Sprinkler systems |
| 22 | Plumbing | Piping, fixtures, equipment |
| 23 | HVAC | Ductwork, equipment, controls |
| 26 | Electrical | Power, lighting, wiring |
| 31 | Earthwork | Excavation, grading, fill *(Added v0.2)* |
| 32 | Exterior Improvements | Paving, site concrete, landscaping *(Added v0.2)* |
| 33 | Utilities | Site utilities, storm drainage *(Added v0.2)* |

---

*This document is a living artifact. It will be updated as the system design evolves through prototyping and testing.*
