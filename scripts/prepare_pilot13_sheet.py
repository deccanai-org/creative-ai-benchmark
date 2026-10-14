"""Prepare bounded Sheet edits from a live-read snapshot; never send writes."""
import copy
import json
from pathlib import Path
from build_v7_annotation_pilot import TASK_IDS, SHEET_EXPORT, BASE_URL

WORK=SHEET_EXPORT.parent
PART_A=[
 'Is the purpose of the work clearly stated?',
 'Is the intended audience identified?',
 'Do the supplied materials leave the commissioned design work for the freelancer to complete?',
 'Does the task provide enough information, usable assets and design direction to begin the requested work?',
 'Does the brief specify the intended use, content, file format, dimensions and relevant export settings for the requested outputs?',
 'Does the task require creative decisions beyond placing supplied images and text into a fixed template?',
 'Is the brief written as a professional client request?',
 'Does the brief clearly distinguish fixed requirements from decisions the designer may make?',
 'Is the brief free of contradictory instructions?'
]
BRAND=[
 'Does the brand identity explain the audience and the impression the design should create?',
 'Does the colour guidance specify which colours are required and where they may be used?',
 'Does the typography guidance identify accessible font files and the required families and weights for the text roles?',
 'Is it clear which supplied identity artwork can be used directly and which reconstruction or redesign is included in the commission?',
 'Is the brand guidance consistent with the brief and the supplied assets?'
]

def has_response(value):
    if isinstance(value,list): return any(has_response(v) for v in value)
    if isinstance(value,dict):
        return any((k in ['BriefRadio','Brief_Justification','AcceptRejectRadio','Assest_comment','verifer_radio','comment_box'] and bool(v)) or has_response(v) for k,v in value.items())
    return False

def main():
    snapshot=json.loads((WORK/'sheet-before.json').read_text())
    fresh=json.loads(SHEET_EXPORT.read_text()); requests=[]
    for sh in snapshot['sheets']:
        name=sh['properties']['title']; sid=sh['properties']['sheetId']
        oldrows=[[next(iter(c.get('userEnteredValue',{}).values()),'') for c in r.get('values',[])] for r in sh['data'][0]['rowData']]
        for row in oldrows[1:]:
            for cell in row:
                if isinstance(cell,str) and cell.startswith('['):
                    assert not has_response(json.loads(cell)),f'Preserve existing annotation responses in {name}; manual merge needed.'
        if name=='Pilot 10 - V7 Annotation':
            rows=fresh[1:]; width=14
        elif name=='updated 10 tasks':
            questions=json.dumps([{'BriefQuestion':f'{i}. {q}','BriefRadio':'','Brief_Justification':''} for i,q in enumerate(PART_A,1)],ensure_ascii=False,separators=(',',':'))
            rows=[[BASE_URL+tid+'.html',questions,i,'','NORMAL'] for i,tid in enumerate(TASK_IDS,1)];width=5
        else:
            rows=[[r[0],r[2],r[3],r[4],r[5],r[6],r[7]] for r in fresh[1:]];width=7
        for row in rows: assert len(row)==width and all(len(str(v))<49000 for v in row)
        requests.append({'updateCells':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':14,'startColumnIndex':0,'endColumnIndex':width},'rows':[{'values':[{'userEnteredValue':{'numberValue':v} if isinstance(v,(int,float)) else {'stringValue':v}} for v in row]} for row in rows],'fields':'userEnteredValue'}})
    payload={'spreadsheet_id':snapshot['spreadsheetId'],'requests':requests}
    (WORK/'sheet-update-pending.json').write_text(json.dumps(payload,ensure_ascii=False))
    (WORK/'evaluation-contract.json').write_text(json.dumps({'part_a':PART_A,'brand_identity':BRAND,'answer_type':'single_yes_no_per_question','no_feedback_prompt':'Name what is missing or unclear and which deliverable it affects.','decision_quality_scope':'Brief and brand identity only, not individual assets.','typography_scope':'Font-file access and role guidance at input review; actual font use at output review.','difficulty_note':'Question 6 tests creative decisions, not uncalibrated difficulty levels.','publication_status':'pending S3 upload permission; not applied to live Sheet'},indent=2))
    print('Prepared 13 rows in each of 3 existing tabs. Live Sheet unchanged. Re-read before applying.')

if __name__=='__main__':main()
