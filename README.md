Sched-MVP – AI-Driven Pastry Kitchen Scheduling System

Author: Spencer
Tech Stack: Python, FastAPI, LLM, Rule Engine
Status: Active Development – Usable MVP

🎯 Project Purpose

Sched-MVP is a production-grade scheduling engine designed specifically for professional pastry kitchens.

The goal is to replace manual scheduling with:

a rules engine (hard + soft constraints),

natural language editing powered by LLMs,

persistent plan storage + modifications,

and upcoming full web deployment.

Unlike academic timetabling demos, Sched-MVP targets real kitchen constraints:
people rotate stations, skill distributions are uneven, holidays matter, and kitchen throughput depends on correct assignments.

🧩 Core Features
✔ Automatic daily schedule generation

Based on:

employee skills

station requirements

shift priority

fallback logic

business rules

✔ Full week/month schedule support

CSV exports available for:

7-day week

full month

✔ Persistent plan storage

Each plan is stored and referenced by a plan_id.

✔ Natural language shift editing (LLM interface)

Example input:
“Move Spencer to GATEAU shift A”
→ validated, patched, and stored.

✔ JSON-based rule configuration:

overtime limits

soft off penalties

required station coverage

priority workers

shift preferences

weekend staffing levels

✔ Future planned upgrades:

LangGraph rule editing UI

FastAPI → Next.js front end

Docker deployment

Role-based access control

More advanced optimization model

📂 Project Structure
sched-mvp/
│
├── app/
│   ├── main.py                # FastAPI entrypoint
│   ├── generate_day.py        # Core day scheduler
│   ├── generate_week.py       # 7-day planner + CSV
│   ├── generate_month.py      # Month planner + CSV
│   ├── week_utils.py          # cross-day constraints
│   ├── plan_service.py        # business logic layer
│   ├── api_llm_patch.py       # API routing layer
│   ├── llm_parser.py          # language → structured patch
│   ├── plan_store.py          # persistent storage engine
│   └── ...
│
├── data/
│   ├── workers.json
│   ├── shifts.json
│   ├── rules.json
│   ├── calendar.json
│   └── ...
│
├── week.csv                   # optional exported result
├── requirements.txt
└── README.md

🛠 Installation
Requirements:

Python 3.11+

Setup:
python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt

🚀 Backend Usage
Start the development server
uvicorn app.main:app --reload


Server URL:

http://127.0.0.1:8000

🔌 API Overview

Sched-MVP provides production-ready scheduling endpoints.

1️⃣ Create a base daily plan

POST /api/plan/create

Request:

{ "date": "2025-11-10" }


Response:

{
  "plan_id": "xxxxx",
  "date": "2025-11-10",
  "plan": { ... }
}

2️⃣ Retrieve a saved plan

GET /api/plan/get?plan_id=XXXX

3️⃣ Preview a natural language patch

POST /api/plan/patch_preview

Request:

{
  "plan_id": "xxxx",
  "text": "Move Spencer to GATEAU A shift"
}


Response returns:

parsed patch

before assignments

after assignments

4️⃣ Apply patch permanently

POST /api/plan/patch_apply

Request:

{
  "plan_id": "xxxx",
  "text": "Move Spencer to GATEAU A shift"
}


On success:

{ "success": true, "saved": true }

5️⃣ Week + Month generation
Generate full week:
python -m app.generate_week 2025-11-10

Export CSV:
/api/week_csv?start_date=YYYY-MM-DD

📅 Data Definition Overview
workers.json example:
{
  "name": "Masuda",
  "role": "employee",
  "skills": ["decor", "knife", "glaze"],
  "station_skills": ["GATEAU", "glaze_and_fruit", "mise_en_place"],
  "shift_prefs": ["1", "2", "A"],
  "max_days_per_week": 5,
  "min_days_per_week": 3,
  "fixed_days_off": ["Tue"]
}


Notes:

shift_prefs are soft preferences

the system will override preferences if necessary

🧠 Rules Engine Design

Example from rules.json:

{
  "fallback_penalty": 1.0,
  "soft_off_penalty": 2.5,
  "max_consecutive_days": 4,
  "stations": {
    "GATEAU": 1,
    "petit_four": 2
  }
}


Sched-MVP does not simply assign randomly:
assignments are scored, optimized, and validated.

🧱 Architectural Layers
FastAPI (Routing)
   ↓
plan_service (Business logic)
   ↓
generate_day (Scheduling Algorithms)
   ↓
JSON rules + worker configs

🔮 Future Development Roadmap
Phase 2 – After MVP

Full web UI (Next.js)

Drag-and-drop schedule editing

Manager permissions

Phase 3 – LangGraph

Rule editing through natural language

Explaining penalties and decisions

Phase 4 – Optimization model

genetic / ILP solver upgrades

multi-objective cost analysis

🌟 Why This Project Matters

Commercial kitchens suffer from:

unpredictable staffing

high training turnover

manual scheduling errors

lack of rule transparency

Sched-MVP aims to:

improve stability

reduce manager workload

formalize knowledge

allow AI-assisted decisions

This is not a toy script.
It is the foundation of a real industry product.