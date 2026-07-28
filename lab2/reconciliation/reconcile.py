import re, csv, json, os
from decimal import Decimal
from collections import Counter

TABLE_NAME="claude-skillrecording-demo"; MATCH_KEY="Email"
OUT=os.path.dirname(os.path.abspath(__file__))
FIELD_MAP={"Email":"Email","First Name":"First Name","Last Name":"Last Name",
  "Email ID":"Email","Phone Number":"Phone Number","Preferred Food":"Preferred Food",
  "T-Shirt Size":"T-Shirt Size","Event Attendance Time":"Event Attendance Time"}
REQUIRED=["Email","First Name","Last Name","Phone Number","Preferred Food","T-Shirt Size","Event Attendance Time"]
RULES={"Email":r"^[^@\s]+@[^@\s]+\.[^@\s]+$","Phone Number":r"^\d{10}$",
  "Preferred Food":["Vegetarian","Non-Vegetarian","Vegan","Gluten-Free"],
  "T-Shirt Size":["XS","S","M","L","XL","XXL"],
  "Event Attendance Time":["8:00 AM - 12:00 PM","1:00 PM - 4:00 PM"]}

def norm(v):
    if v is None: return ""
    if isinstance(v,(int,float,Decimal)): v=format(Decimal(str(v)).normalize(),'f')
    return re.sub(r"\s+"," ",str(v)).strip().lower()

def validate(row):
    errs=[]
    for f in REQUIRED:
        if not str(row.get(f,"")).strip(): errs.append(f+": missing")
    for f,rule in RULES.items():
        val=str(row.get(f,"")).strip()
        if not val: continue
        if isinstance(rule,list):
            if val not in rule: errs.append(f+": '"+val+"' not allowed")
        elif not re.match(rule,val): errs.append(f+": '"+val+"' bad format")
    return errs

responses=json.load(open(os.path.join(OUT,"form_responses.json")))
ddb_raw=json.load(open(os.path.join(OUT,"ddb_items.json")))
ddb={norm(k):v for k,v in ddb_raw.items()}

rows=[]
for r in responses:
    item=ddb.get(norm(r.get(MATCH_KEY)))
    for ff,attr in FIELD_MAP.items():
        fv=str(r.get(ff,"")).strip()
        dv="" if item is None else item.get(attr,"")
        if item is None: st,note="NOT_IN_DDB","no DynamoDB item for "+MATCH_KEY
        elif not fv and dv in (None,""): st,note="MISSING_BOTH","manual follow-up"
        elif not fv: st,note,fv="MISSING→FILLED","sourced from system of record",str(dv)
        elif dv in (None,""): st,note="MISMATCH","blank in DynamoDB"
        elif norm(fv)==norm(dv): st,note="MATCH",""
        else: st,note="MISMATCH","differs"
        rows.append({"match_key":r.get(MATCH_KEY,""),"field":ff,"form_value":fv,
                     "dynamodb_value":"" if item is None else str(dv),"status":st,"note":note})
    for e in validate(r):
        rows.append({"match_key":r.get(MATCH_KEY,""),"field":"_validation","form_value":"",
                     "dynamodb_value":"","status":"VALIDATION_FAIL","note":e})

csv_path=os.path.join(OUT,"Reconciliation_Results.csv")
with open(csv_path,"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["match_key","field","form_value","dynamodb_value","status","note"])
    w.writeheader(); w.writerows(rows)

c=Counter(x["status"] for x in rows)
per_resp={}
for x in rows:
    per_resp.setdefault(x["match_key"],set()).add(x["status"])
print("=== RECONCILIATION SUMMARY ===")
print("Table:",TABLE_NAME,"| Match key:",MATCH_KEY)
print("Total form responses:",len(responses),"| DDB items:",len(ddb))
print("Total field comparisons:",sum(1 for x in rows if x['field']!='_validation'))
print("-- field-level status counts --")
for k in ["MATCH","MISMATCH","MISSING→FILLED","NOT_IN_DDB","MISSING_BOTH","VALIDATION_FAIL"]:
    print(f"  {k}: {c.get(k,0)}")
attn=[m for m,s in per_resp.items() if s & {"MISMATCH","NOT_IN_DDB","MISSING_BOTH","VALIDATION_FAIL"}]
print("-- rows needing manual attention:",len(attn),"--")
for m in sorted(attn):
    print("  ",m,"->",",".join(sorted(per_resp[m] & {"MISMATCH","NOT_IN_DDB","MISSING_BOTH","VALIDATION_FAIL"})))
print("CSV:",csv_path)
