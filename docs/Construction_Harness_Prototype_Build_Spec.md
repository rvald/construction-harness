# Construction Estimation Harness — Prototype Build Specification

**Version:** 1.0
**Date:** July 1, 2026
**Purpose:** This document provides a complete technical specification for building a prototype data ingestion pipeline for a construction estimation harness. It is intended to be handed to a coding agent for pair-programming implementation.

---

## 1. Objective

Build a Python prototype that validates the data ingestion architecture described in the companion document `Construction_Estimation_Harness_Data_Ingestion_Architecture.md` (v0.2). The prototype processes a real construction bid package (UCCS Cybersecurity and Space Ecosystem Expansion) and produces a structured knowledge graph connecting building elements across drawings and specifications.

The goal is hypothesis validation, not production readiness. Prioritize correctness and learning over performance, scalability, or polish.

---

## 2. Input Documents

Two PDF files comprise the complete bid package:

### 2.1 Drawing Set
- **Filename:** `2021-0525_UCCS_BID_SET_-_Drawings.pdf`
- **Pages:** 133
- **Format:** Vector PDF with embedded fonts (created in Bluebeam Revu x64)
- **Page size:** 30" × 42" (ARCH E1), landscape orientation (90° rotation)
- **Content:** Complete multi-discipline construction drawing set
- **Disciplines covered:** General (4 sheets), Structural (1), Architectural (38), Architectural Finishes (4), Architectural Demo (2), Fire Protection (2), Plumbing (6), Mechanical (19), Electrical (19), Technology (20), Security (5)

### 2.2 Project Manual (Specifications)
- **Filename:** `2021-0525_UCCS_BID_SET_-_Project_Manual.pdf`
- **Pages:** 1,036
- **Format:** Text PDF with embedded fonts (created in Adobe Acrobat Pro DC)
- **Page size:** 8.5" × 11" (US Letter), portrait
- **Content:** Full CSI-formatted project specifications
- **Divisions covered:** 00 (Procurement), 01 (General Requirements), 02 (Existing Conditions), 03 (Concrete), 06 (Wood/Plastics/Composites), 07 (Thermal/Moisture), 08 (Openings), 09 (Finishes), 10 (Specialties), 12 (Furnishings), 21 (Fire Suppression), 22 (Plumbing), 23 (HVAC), 26 (Electrical), 27 (Communications)
- **Divisions explicitly marked "Not Applicable":** 04 (Masonry), 05 (Metals), 11 (Equipment), 13 (Special Construction), 14 (Conveying Equipment), 25 (Integrated Automation), 28 (Electronic Safety/Security), 31 (Earthwork), 32 (Exterior Improvements)

### 2.3 Project Context
- **Project:** UCCS Cybersecurity and Space Ecosystem Expansion
- **Location:** 3650 North Nevada Ave, Colorado Springs, CO 80907
- **Owner:** University of Colorado, Colorado Springs
- **Architect:** SmithGroup, Denver, CO
- **Structural Engineer:** Martin/Martin, Inc., Lakewood, CO
- **Project Number:** 12654.000
- **Issue Date:** May 4, 2021 (Bid Set), with Addendum 01 (May 2021)
- **Scope:** Renovation of approximately 26,877 GSF of an existing 132,568 GSF commercial building. North Building (~18,735 NSF) and South Building (~5,511 NSF).
- **Construction Type:** IIB
- **Design Stage:** Construction Documents (CD)

---

## 3. Technology Stack

### 3.1 Required
- **Language:** Python 3.11+
- **PDF text extraction:** pdfplumber (primary), PyMuPDF/fitz (secondary for binary-level access)
- **Table extraction:** pdfplumber (integrated table detection)
- **Data classes:** Pydantic (for structured models with validation)
- **Testing:** pytest
- **Exploration:** Jupyter notebooks

### 3.2 Optional (introduce as needed)
- **Graph database:** Neo4j with neo4j Python driver (can defer — start with in-memory graph using NetworkX or plain dicts)
- **Full-text search:** Simple in-memory search initially (defer Elasticsearch)
- **AI model calls:** Anthropic Python SDK for Claude API (Phase 4 only — defer until Phases 2-3 are solid)

### 3.3 Not Needed for Prototype
- Go, Rust, or any compiled language
- Docker, Kubernetes, or any containerization
- Cloud storage (S3/MinIO)
- Pipeline orchestration (Airflow/Prefect)
- Frontend/UI

---

## 4. Project Structure

```
construction-harness/
├── README.md
├── requirements.txt
├── pyproject.toml
│
├── data/
│   └── uccs/
│       ├── drawings.pdf          # symlink or copy of drawing set
│       └── project_manual.pdf    # symlink or copy of project manual
│
├── notebooks/
│   ├── 01_explore_project_manual.ipynb
│   ├── 02_explore_drawings.ipynb
│   ├── 03_explore_door_schedule.ipynb
│   └── 04_explore_binary_extraction.ipynb
│
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── project.py            # Project, Sheet, FileRegistry
│   │   ├── spec.py               # SpecDivision, SpecSection, SpecClause
│   │   ├── schedule.py           # DoorEntry, FinishEntry, PartitionType
│   │   ├── element.py            # BuildingElement, ElementInstance
│   │   ├── drawing.py            # TextObject, GeometricPrimitive, ExtractedSymbol
│   │   └── graph.py              # GraphNode, GraphEdge, KnowledgeGraph
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── phase1_intake.py
│   │   ├── phase2_spec_parser.py
│   │   ├── phase2_schedule_parser.py
│   │   ├── phase2_abbreviation_parser.py
│   │   ├── phase2_legend_parser.py
│   │   ├── phase2_bid_structure_parser.py
│   │   ├── phase3_sheet_classifier.py
│   │   ├── phase4_binary_extractor.py
│   │   ├── phase4_text_extractor.py
│   │   ├── phase5_graph_builder.py
│   │   └── orchestrator.py       # Runs phases in sequence
│   │
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── gates.py              # Phase boundary validation checks
│   │   └── domain_rules.py       # Construction-specific business rules
│   │
│   └── utils/
│       ├── __init__.py
│       ├── pdf_utils.py          # Common PDF operations
│       └── text_utils.py         # Text cleaning, regex patterns
│
├── tests/
│   ├── __init__.py
│   ├── test_spec_parser.py
│   ├── test_schedule_parser.py
│   ├── test_abbreviation_parser.py
│   ├── test_sheet_classifier.py
│   ├── test_binary_extractor.py
│   ├── test_graph_builder.py
│   ├── test_validation_gates.py
│   └── fixtures/
│       ├── expected_toc.json
│       ├── expected_door_schedule.json
│       ├── expected_abbreviations.json
│       └── expected_sheet_registry.json
│
└── output/
    ├── extracted/                 # Pipeline output artifacts
    └── reports/                  # Validation reports
```

---

## 5. Build Sequence

Build in this exact order. Each milestone must pass its tests before proceeding to the next. This sequence is designed so that each step produces output that the next step depends on.

---

### Milestone 1: Project Setup and PDF Exploration

**Goal:** Set up the project, install dependencies, and explore both PDFs interactively to understand the raw data before writing any pipeline code.

**Tasks:**
1. Initialize the project structure as defined in Section 4.
2. Create `requirements.txt` with: `pdfplumber`, `pymupdf`, `pydantic`, `pytest`, `jupyter`, `networkx`.
3. Create exploration notebook `01_explore_project_manual.ipynb`:
   - Open the project manual with pdfplumber.
   - Extract text from pages 5-10 (the Table of Contents). Print raw text and inspect structure.
   - Extract text from a single spec section (pages ~350-365, Section 081113 Hollow Metal Doors). Inspect Part 1/Part 2/Part 3 structure.
   - Document findings: What does the text look like? Are there consistent patterns for section headers, part headers, clause numbering?
4. Create exploration notebook `02_explore_drawings.ipynb`:
   - Open the drawings PDF with pdfplumber.
   - Extract text from page 2 (drawing index / sheet list). Inspect the table structure.
   - Extract text from page 6 (architectural abbreviations, A0.1). Note the multi-column layout.
   - Extract text from page 14 (floor plan, A2.1.1). See what text objects exist on a floor plan and their positions.
   - Extract text from page 38 (door schedule, A9.3.1). Try `page.extract_tables()` on this page and inspect the result.
   - Use PyMuPDF to extract geometric paths from page 14. Count the number of path objects. This previews Phase 4 binary extraction.

**Acceptance Criteria:**
- Both PDFs open without errors.
- Text extraction produces readable output from both documents.
- The notebooks contain documented observations about data structure and quality.

---

### Milestone 2: Data Models

**Goal:** Define the Pydantic data models that represent the pipeline's structured output. These models are the contract between pipeline phases — each phase produces instances of these models that downstream phases consume.

**Tasks:**
1. Implement `src/models/project.py`:

```python
class FileInfo(BaseModel):
    """A single file in the bid package."""
    filename: str
    filepath: str
    file_type: Literal["drawings", "project_manual", "other"]
    format: Literal["pdf_vector", "pdf_scanned", "dwg", "ifc", "rvt", "unknown"]
    page_count: int
    file_size_bytes: int
    checksum_sha256: str

class SheetEntry(BaseModel):
    """A single entry from the drawing index."""
    sheet_number: str           # e.g., "A2.1.1"
    sheet_title: str            # e.g., "LEVEL 1 - FLOOR PLAN - OVERALL"
    discipline: str             # e.g., "Architectural"
    drawing_type: str | None    # e.g., "Floor Plan", "Section", "Detail", "Schedule"
    pdf_page_number: int | None # 1-indexed page in the PDF

class ProjectInfo(BaseModel):
    """Top-level project metadata."""
    project_name: str
    project_number: str
    location: str
    owner: str
    architect: str
    structural_engineer: str
    design_stage: str           # "SD", "DD", "CD"
    issue_date: str
    building_area_gsf: int | None
    construction_type: str | None
    files: list[FileInfo]
    sheet_registry: list[SheetEntry]
```

2. Implement `src/models/spec.py`:

```python
class SpecClause(BaseModel):
    """A single clause within a spec section part."""
    clause_id: str              # e.g., "2.01", "2.02.A.1"
    text: str
    products: list[str]         # Extracted product/manufacturer names
    standards: list[str]        # Referenced standards (ASTM, ANSI, etc.)

class SpecPart(BaseModel):
    """Part 1, 2, or 3 of a spec section."""
    part_number: int            # 1, 2, or 3
    part_title: str             # "GENERAL", "PRODUCTS", "EXECUTION"
    clauses: list[SpecClause]

class SpecSection(BaseModel):
    """A single CSI specification section."""
    section_number: str         # e.g., "081113"
    section_title: str          # e.g., "HOLLOW METAL DOORS AND FRAMES"
    division_number: str        # e.g., "08"
    division_title: str         # e.g., "OPENINGS"
    parts: list[SpecPart]
    page_range: tuple[int, int] # Start and end pages in the PDF
    raw_text: str               # Full raw text of the section

class SpecTOC(BaseModel):
    """Table of contents for the project manual."""
    divisions: list[dict]       # [{number, title, sections: [{number, title}], applicable: bool}]
    total_sections: int
```

3. Implement `src/models/schedule.py`:

```python
class DoorEntry(BaseModel):
    """A single row from the door schedule."""
    door_mark: str              # e.g., "N101A"
    fire_rating_minutes: int | None
    width: str                  # e.g., "3' - 0\""
    height: str                 # e.g., "7' - 8\""
    door_elevation_type: str    # e.g., "FG" (full glass)
    door_material: str          # e.g., "AL & G" (aluminum & glass)
    door_finish: str            # e.g., "AL - Clear Anodized"
    frame_elevation_type: str | None
    frame_material: str         # e.g., "AL" (aluminum)
    frame_finish: str           # e.g., "AL - Clear Anodized"
    hardware_set: str           # e.g., "AL-01"
    glass_film: str | None      # e.g., "GLF-2"
    glass_type: str | None      # e.g., "GL-5"
    comments: str | None

class FinishEntry(BaseModel):
    """A single row from the room finish schedule."""
    room_number: str            # e.g., "N101"
    room_name: str              # e.g., "STUDENT LIVING ROOM"
    floor_finish: str           # e.g., "CPT-1"
    base_finish: str            # e.g., "RB-2"
    wall_finish: str            # e.g., "P-1"
    ceiling_finish: str         # e.g., "ACT-1"
    comments: str | None

class AbbreviationEntry(BaseModel):
    """A single abbreviation definition."""
    abbreviation: str           # e.g., "GWB"
    definition: str             # e.g., "GYPSUM WALL BOARD"
```

4. Implement `src/models/graph.py`:

```python
class GraphNode(BaseModel):
    """A node in the knowledge graph."""
    id: str                     # Unique identifier
    node_type: str              # "spec_section", "door", "room", "sheet", "material", etc.
    properties: dict            # Flexible properties bag
    source_file: str            # Provenance: which file
    source_page: int | None     # Provenance: which page
    confidence: float           # 0.0 to 1.0

class GraphEdge(BaseModel):
    """A relationship in the knowledge graph."""
    source_id: str
    target_id: str
    relationship: str           # "HAS_TYPE", "IS_SPECIFIED_IN", "APPEARS_ON", etc.
    properties: dict | None

class KnowledgeGraph(BaseModel):
    """The complete project knowledge graph."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # Methods: add_node, add_edge, find_node, traverse, query, export_json, etc.
```

**Acceptance Criteria:**
- All models instantiate without errors with sample data.
- Pydantic validation catches invalid data (e.g., empty required fields).
- Models serialize to and from JSON cleanly.

---

### Milestone 3: Phase 2a — Specification TOC Parser

**Goal:** Parse the Table of Contents from the project manual into a structured `SpecTOC` object. This is the index that tells us what spec sections exist and guides navigation to individual sections.

**Source Document:** Project Manual, pages 5-10 (approximately).

**Implementation: `src/pipeline/phase2_spec_parser.py`**

**Parsing Logic:**
1. Extract text from the TOC pages using pdfplumber.
2. Identify division headers matching the pattern: `DIVISION XX - TITLE` or `DIVISION XX – TITLE` (note: both hyphen and em-dash are used).
3. Identify section entries matching the pattern: `SECTION XXXXXX - TITLE` or `SECTION XXXXXX.XX - TITLE`.
4. Associate each section with its parent division.
5. Identify divisions marked "NOT APPLICABLE" — these are still recorded but flagged as not applicable.
6. Determine page ranges for each section by finding the section header in the full document text.

**Expected Output — Ground Truth:**
- 24 divisions listed (00 through 32, with gaps)
- 9 divisions marked "NOT APPLICABLE" (04, 05, 11, 13, 14, 25, 28, 31, 32)
- 15 divisions with active sections
- Total active sections: approximately 90+ (the TOC lists 124 lines including division headers and non-applicable markers; the actual section count needs verification during implementation)
- Division 08 (Openings) should contain exactly 9 sections: 081113, 081416, 084113, 084229.33, 086300, 087100, 088000, 088300, 088813

**Test File: `tests/test_spec_parser.py`**
```python
def test_toc_parsing():
    toc = parse_spec_toc("data/uccs/project_manual.pdf")
    assert toc.total_sections > 80
    div_08 = next(d for d in toc.divisions if d["number"] == "08")
    assert div_08["title"] == "OPENINGS"
    assert len(div_08["sections"]) == 9
    assert any(s["number"] == "081113" for s in div_08["sections"])

def test_not_applicable_divisions():
    toc = parse_spec_toc("data/uccs/project_manual.pdf")
    div_04 = next(d for d in toc.divisions if d["number"] == "04")
    assert div_04["applicable"] == False

def test_all_divisions_present():
    toc = parse_spec_toc("data/uccs/project_manual.pdf")
    expected_divisions = ["00","01","02","03","04","05","06","07","08","09","10","11","12","13","14","21","22","23","25","26","27","28","31","32"]
    actual_divisions = [d["number"] for d in toc.divisions]
    assert actual_divisions == expected_divisions
```

---

### Milestone 4: Phase 2b — Individual Spec Section Parser

**Goal:** Parse individual specification sections into the `SpecSection` model, extracting the Part 1/Part 2/Part 3 structure and individual clauses.

**Source Document:** Project Manual. Start with Section 081113 (Hollow Metal Doors and Frames) as the test case.

**Parsing Logic:**
1. Given a section number and approximate page range (from TOC parsing), extract the full text of that section.
2. Identify section boundaries: starts with `SECTION XXXXXX - TITLE` and ends at the next `SECTION` header or `END OF SECTION`.
3. Split into parts using the pattern `PART X - TITLE` (where X is 1, 2, or 3).
4. Within each part, identify top-level clauses using the pattern `X.X` followed by a title in all caps (e.g., `1.1 RELATED DOCUMENTS`, `2.1 PERFORMANCE REQUIREMENTS`).
5. Extract product and manufacturer references from Part 2 clauses.
6. Extract referenced standards (ASTM, ANSI, NAAMM, SDI, etc.).

**Test Case — Section 081113 Ground Truth:**
- Section title: "HOLLOW METAL DOORS AND FRAMES"
- Division: 08 - Openings
- Contains Part 1 (GENERAL), Part 2 (PRODUCTS), Part 3 (EXECUTION)
- Part 1 should contain clauses for: RELATED DOCUMENTS, SUMMARY, DEFINITIONS, COORDINATION, PREINSTALLATION MEETINGS, ACTION SUBMITTALS, and more
- Part 2 should reference manufacturers and material specifications
- Part 3 should contain installation requirements

**Additional Test Cases (implement after 081113 works):**
- Section 092900 (Gypsum Board) — high-detail section with many product specs
- Section 099123 (Interior Painting) — references finish codes used in the finish schedule
- Section 087100 (Door Hardware) — links to hardware sets in the door schedule

---

### Milestone 5: Phase 2c — Drawing Index Parser

**Goal:** Parse the drawing index from the drawings PDF into a list of `SheetEntry` objects, creating the sheet registry.

**Source Document:** Drawings PDF, page 2 (sheet G1.1).

**Parsing Logic:**
1. Extract tables from page 2 using pdfplumber's `page.extract_tables()`.
2. The drawing index is a two-column table split across the page. Each entry has a sheet number and sheet title.
3. Parse each row into a `SheetEntry` with sheet number and title.
4. Derive the discipline from the sheet number prefix:
   - G = General
   - S = Structural
   - A, AD, AF = Architectural (AD = Demo, AF = Finishes)
   - FP = Fire Protection
   - P, PD = Plumbing (PD = Demo)
   - M, MD = Mechanical (MD = Demo)
   - E, ED, EMP = Electrical (ED = Demo, EMP = M&P Equipment Power)
   - T = Technology
   - Y = Security
5. Derive the drawing type from the sheet title using keyword matching:
   - "FLOOR PLAN" → Floor Plan
   - "REFLECTED CEILING PLAN" → Reflected Ceiling Plan
   - "ELEVATION" → Elevation
   - "SECTION" → Section
   - "DETAIL" → Detail
   - "SCHEDULE" → Schedule
   - "ABBREVIATIONS" or "SYMBOLS" → Reference
   - "DEMOLITION" → Demolition Plan
   - "ENLARGED" → Enlarged Plan
6. Map each sheet entry to its PDF page number by scanning title blocks or using sequential page numbering (page 1 = cover sheet G0.0, page 2 = G1.1, etc.).

**Expected Output — Ground Truth:**
- 133 sheet entries total
- Discipline breakdown: General (4), Structural (1), Architectural (44 including AD and AF), Fire Protection (2), Plumbing (8 including PD), Mechanical (22 including MD), Electrical (27 including ED and EMP), Technology (20), Security (5)
- Sheet A2.1.1 should have title "LEVEL 1 - FLOOR PLAN - OVERALL", discipline "Architectural", type "Floor Plan"
- Sheet A9.3.1 should have title "DOOR AND FRAME SCHEDULE & ELEVATIONS", discipline "Architectural", type "Schedule"

---

### Milestone 6: Phase 2d — Abbreviation Parser

**Goal:** Parse the architectural abbreviation list from the drawings into a dictionary of abbreviation definitions.

**Source Document:** Drawings PDF, page 6 (sheet A0.1).

**Parsing Logic:**
1. Extract text from page 6 with coordinate positions using pdfplumber.
2. The abbreviation list occupies the left portion of the sheet in a multi-column layout. Each entry follows the pattern: `ABBREV` (tab or space) `DEFINITION`.
3. Parse into `AbbreviationEntry` objects.
4. Also extract the architectural symbol definitions from the right portion of the page (these are graphical symbols with text labels — extract at minimum the text labels and their descriptions).

**Expected Output — Partial Ground Truth (verify during implementation):**
- Should include entries like: ACT = ACOUSTICAL CEILING TILE, CMU = CONCRETE MASONRY UNIT, GWB = GYPSUM WALL BOARD (or similar), HM = HOLLOW METAL, WD = WOOD, AL = ALUMINUM
- Total abbreviation count: estimate 200+ entries based on visual inspection of the dense multi-column layout

---

### Milestone 7: Phase 2e — Door Schedule Parser

**Goal:** Parse the door and interior opening schedule from the drawings into structured `DoorEntry` records.

**Source Document:** Drawings PDF, page 38 (sheet A9.3.1).

**Parsing Logic:**
1. Use pdfplumber to extract the table from page 38.
2. The door schedule is a large table in the upper portion of the sheet with columns: NUMBER, FIRE RATING (MINUTES), WIDTH, HEIGHT, ELEVATION (door), MATERIAL (door), FINISH (door), ELEVATION (frame), MATERIAL (frame), FINISH (frame), HARDWARE SET, GLASS FILM, GLASS TYPE, SPECIAL NOTES AND COMMENTS.
3. Parse each row into a `DoorEntry` object.
4. Handle the following complications:
   - Some cells may be empty (e.g., fire rating is blank for non-rated doors).
   - Door marks follow the pattern: building prefix (N for North, S for South) + room number + letter suffix (A, B, C, etc.).
   - The table may not extract cleanly due to the dense layout — implement confidence scoring on extraction quality.

**Expected Output — Ground Truth:**
- Approximately 58 unique door marks in the schedule.
- All door marks should start with "N" (North Building) or "S" (South Building).
- Door N101A should be: 6'-0" wide, 8'-9 1/2" tall, aluminum and glass, clear anodized finish, hardware set AL-11, glass type GL-3.
- Door N107B should be: 6'-0" wide, 7'-0" tall, wood door (WD), wood veneer finish (WV-1), hollow metal frame (HM), hardware set 205.

---

### Milestone 8: Phase 2f — Finish Schedule Parser

**Goal:** Parse the room finish schedule from the drawings into structured `FinishEntry` records.

**Source Document:** Drawings PDF, page 49 (sheet AF2.4). The room finish schedule table is in the lower portion of this page.

**Parsing Logic:**
1. Extract the room finish schedule table from page 49.
2. Columns: NUMBER, NAME, FLOOR, BASE, WALL, CEILING, SPECIAL NOTES AND COMMENTS.
3. Parse into `FinishEntry` objects.
4. Also parse the Applied Finish List from the upper portion of the same page — this defines what each finish code means (e.g., P-1 = "TYPE: GENERAL PAINT, MANUFACTURE: DUNN EDWARDS, COLOR: ...").

**Expected Output — Ground Truth:**
- Room finish entries for all named rooms in the project (estimate 30-50 rooms based on floor plan inspection).
- Each room should have finish codes for floor, base, wall, and ceiling.
- Finish codes should resolve against the applied finish list (e.g., CPT-1, RB-2, P-1, ACT-1 should all have definitions in the applied finish list).

---

### Milestone 9: Phase 3 — Sheet Classification

**Goal:** Extract title block metadata from drawing sheets and verify against the sheet registry built in Milestone 5.

**Source Document:** Drawings PDF, all pages.

**Parsing Logic:**
1. For each page in the drawings PDF, extract text from the title block region. The SmithGroup title block occupies a vertical strip on the right side of each sheet.
2. Extract: sheet number, sheet title, project number, issue date, scale, revision information.
3. The title block on this project has a consistent format — the sheet number is in a box at the bottom-right corner, and the sheet title is directly above it.
4. Cross-reference extracted sheet metadata against the sheet registry from Milestone 5. Flag any discrepancies.

**Implementation Note:**
- Start with a sample of 10-15 sheets across different disciplines rather than all 133.
- Pick: G1.1 (page 2), A0.1 (page 6), A2.1.1 (page 14), A2.1.2 (page 15), A9.2.1 (page 35), A9.3.1 (page 38), AF2.4 (page 49), FP0.1 (page 50), P0.1 (page 52), M0.1 (page ~60), E0.1 (page ~72).
- The title block position may vary slightly between disciplines if different subconsultants used different templates.

---

### Milestone 10: Phase 4 — Binary Drawing Extraction (Proof of Concept)

**Goal:** Extract text objects and geometric primitives from a single floor plan page using binary-level PDF parsing. This is the most uncertain part of the pipeline — the goal is to learn what data is available, not to build a complete extractor.

**Source Document:** Drawings PDF, page 14 (sheet A2.1.1 — Level 1 Floor Plan Overall).

**Parsing Logic:**
1. Using PyMuPDF (fitz), extract all text objects from page 14 with their exact coordinates, font, size, and rotation. Store as `TextObject` instances.
2. Classify text objects by probable type:
   - **Room names/numbers:** Text centered in enclosed regions, typically uppercase. Look for patterns matching room names visible on the plan (e.g., "OFFICE", "CLASSROOM", "CYBER RANGE LAB", "STUDENT LIVING ROOM").
   - **Dimension strings:** Text containing feet/inch notation (e.g., patterns like `XX' - X"`).
   - **Grid labels:** Single letters (A through K) or numbers (1 through 8) at sheet margins. This project uses grid labels like S-1 through S-8 and N-1 through N-7 (visible on the floor plan).
   - **Door marks:** Text matching the pattern `N\d{3}[A-Z]?` near door symbol locations.
   - **Sheet references:** Text matching patterns like `A9.3.1` or `SHEET A2.1.4`.
3. Using PyMuPDF, extract all drawing paths (vector geometry) from page 14. Count them, categorize by type (lines, curves, rectangles), and note their coordinates. This is exploratory — the goal is to understand the raw geometry data, not to classify all elements.
4. Attempt basic pattern matching:
   - Identify probable wall lines: pairs of parallel lines of consistent weight.
   - Identify grid lines: long lines spanning the full drawing area.
   - Identify the drawing border: the outermost rectangle.

**Expected Output:**
- A list of all text objects on the floor plan with positions and classifications.
- A count of geometric primitives by type.
- Observations documented about what can and cannot be determined from binary data alone.
- This milestone produces *learning*, not a production-quality extractor.

---

### Milestone 11: Phase 5 — Knowledge Graph Assembly

**Goal:** Take the structured data from Milestones 3-9 and assemble it into a connected knowledge graph. Demonstrate end-to-end traceability from a building element through schedules to spec sections.

**Implementation: `src/pipeline/phase5_graph_builder.py`**

**Graph Construction:**
1. Create **Spec Section nodes** from the parsed TOC and individual sections (Milestones 3-4).
2. Create **Sheet nodes** from the sheet registry (Milestone 5).
3. Create **Door nodes** from the door schedule (Milestone 7). Each door entry becomes a node.
4. Create **Room nodes** from the finish schedule (Milestone 8). Each room becomes a node.
5. Create **Abbreviation nodes** from the parsed abbreviation list (Milestone 6).
6. Create **edges**:
   - Door → Spec Section: Door material "HM" (Hollow Metal) → Section 081113. Door material "WD" (Wood) → Section 081416. Hardware set → Section 087100. Glass type → Section 088000 or 088813.
   - Door → Room: Door mark N101A → Room N101 (derived from the door mark prefix).
   - Room → Spec Section: Room finish codes → corresponding spec sections (e.g., floor finish CPT-1 is carpet tile → Section 096813; paint P-1 → Section 099123; ACT-1 is acoustical ceiling → Section 095113).
   - Sheet → Door/Room: Elements appear on specific sheets.
   - Spec Section → Spec Section: Cross-references between sections (e.g., Section 081113 references Section 087100 for hardware).

**Validation Queries (implement as methods on the KnowledgeGraph class):**
1. `get_door_full_spec(door_mark)` — Given a door mark, return all connected spec sections (door, frame, hardware, glazing).
2. `get_room_full_spec(room_number)` — Given a room number, return all finish spec sections and door specs for doors in that room.
3. `find_orphan_doors()` — Doors in the schedule not connected to any room.
4. `find_orphan_specs()` — Spec sections not connected to any element.
5. `find_missing_connections()` — Elements with material codes that couldn't be resolved to spec sections.

**Acceptance Test — The "Door N107B" Test:**

This is the end-to-end validation. For door N107B, the system should be able to report:
- Door N107B is a 6'-0" × 7'-0" wood door (WD) in a hollow metal frame (HM).
- The door itself is specified in Section 081416 (Flush Wood Doors).
- The frame is specified in Section 081113 (Hollow Metal Doors and Frames).
- The door hardware (set 205) is specified in Section 087100 (Door Hardware).
- The door has no glass (N/A).
- The door is located in room N107 (or derived room, depending on naming convention).
- The door appears on a drawing sheet (A2.1.x series floor plan).
- Each of these connections traces back to a source document and page.

---

### Milestone 12: Validation Gates and Reporting

**Goal:** Implement validation checks at each phase boundary and produce a summary report.

**Implementation: `src/validation/gates.py`**

**Validation Checks:**
1. **Post-Phase 2:** Spec TOC section count matches expected range. All divisions accounted for. Door schedule has >50 entries. Finish schedule has >25 entries. Abbreviation list has >100 entries.
2. **Post-Phase 3:** Sheet count matches drawing index (133). All disciplines represented. No unclassified sheets in the sample set.
3. **Post-Phase 5:** Graph connectivity — no isolated nodes (every node has at least one edge). Door-to-spec connections: >90% of doors resolve to at least one spec section. Room-to-finish connections: >90% of rooms have finish codes that resolve to finish definitions.

**Report Output:** A JSON report summarizing:
- Total nodes and edges by type.
- Connection success rates.
- List of unresolved items (orphan nodes, missing connections).
- Confidence score distribution.

---

## 6. Key Implementation Notes

### 6.1 PDF Page Numbering
- pdfplumber and PyMuPDF both use **0-indexed** page numbers.
- The document references in this spec use **1-indexed** page numbers (matching what you see in a PDF viewer).
- Always be explicit: `page = pdf.pages[page_number - 1]` when converting from this spec to code.

### 6.2 The Drawings PDF Has Rotated Pages
- The drawings PDF has `Page rot: 90` (landscape orientation via rotation).
- pdfplumber handles this automatically for text extraction.
- When extracting coordinates, be aware that the coordinate system may be rotated. Test with a known text object (e.g., the sheet number in the title block) to verify coordinate interpretation.

### 6.3 Text Extraction Challenges to Expect
- The project manual has clean, consistent text. Parsing should be reliable.
- The drawings have text at various angles, sizes, and positions. Dimension text may include special characters for feet (') and inches (").
- Schedule tables on drawing sheets are vector-drawn, not HTML tables. pdfplumber's table extraction works well on some but may struggle on others. If automatic table extraction fails, fall back to extracting text objects with coordinates and reconstructing the table structure spatially.

### 6.4 Iterative Development Pattern
For each milestone:
1. **Explore** in a Jupyter notebook first — try different extraction approaches, see what the raw data looks like.
2. **Implement** the cleanest approach as a pipeline module.
3. **Test** against ground truth data from this spec and from visual inspection of the source documents.
4. **Document** what worked, what didn't, and what assumptions were made.

### 6.5 Don't Over-Engineer
- Use simple Python dicts and lists where Pydantic models feel heavy.
- Use NetworkX for the graph instead of Neo4j until you need persistence.
- Use `print()` debugging over complex logging until you need structured logs.
- Write helper functions, not frameworks.
- If something takes more than a day to get working, step back and ask whether the approach is wrong, not whether the implementation is wrong.

---

## 7. Definition of Done

The prototype is complete when:

1. The pipeline processes both UCCS PDFs without manual intervention.
2. The spec TOC is parsed into a structured index with all divisions and sections.
3. At least 3 spec sections are fully parsed with Part 1/2/3 structure (081113, 087100, 092900).
4. The door schedule is extracted with >90% accuracy against ground truth.
5. The room finish schedule is extracted with >90% accuracy.
6. The abbreviation list is extracted with >80% accuracy.
7. A sheet registry of all 133 sheets is built with discipline classification.
8. A knowledge graph connects doors to spec sections, rooms to finish specs, and elements to sheets.
9. The "Door N107B" end-to-end test passes.
10. A validation report is generated summarizing extraction quality and graph connectivity.

---

## 8. Companion Documents

The following documents provide architectural context for this prototype. They are not required for implementation but explain the design rationale:

- `Construction_Estimation_Harness_Data_Ingestion_Architecture.md` (v0.2) — The full data ingestion architecture this prototype validates.
- `CEQuest: Benchmarking Large Language Models for Construction Estimation` (research paper) — Demonstrates that current LLMs achieve <76% accuracy on construction estimation questions, motivating the need for structured data extraction rather than direct LLM interpretation.

---

*This specification is the complete brief for building the prototype. Start at Milestone 1 and proceed sequentially. Each milestone builds on the previous one. Do not skip milestones or build ahead — the learning from each step informs the next.*
