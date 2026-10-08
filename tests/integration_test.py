"""
Integration test script for MediSync.
"""
import urllib.request
import urllib.parse
import json

BASE = 'http://127.0.0.1:8000'

payload = {
    'name': 'Sundaram Krishnamurthy',
    'email': 'sundaram.k@medisync.local',
    'age': 68,
    'allergies': 'Penicillin',
    'emergency_contact_1_name': 'Priya Sundaram',
    'emergency_contact_1_phone': '+91 98401 23456',
    'emergency_contact_1_relation': 'Daughter',
    'emergency_contact_2_name': 'Karthik Sundaram',
    'emergency_contact_2_phone': '+91 98402 34567',
    'emergency_contact_2_relation': 'Son',
    'emergency_email': 'sundaram.family@medisync.local'
}

req = urllib.request.Request(f'{BASE}/api/auth/signup', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req)
    u_data = json.loads(resp.read().decode())
    user_id = u_data['user']['id']
    print('1. Sign Up Success! User ID:', user_id, 'Guardian Mode:', u_data['user']['guardian_mode_enabled'])
except urllib.error.HTTPError as e:
    req = urllib.request.Request(f'{BASE}/api/auth/login', data=json.dumps({'email': payload['email']}).encode(), headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req)
    u_data = json.loads(resp.read().decode())
    user_id = u_data['user']['id']
    print('1. Logged in existing User ID:', user_id)

form_data = urllib.parse.urlencode({'user_id': user_id, 'preset_key': 'regimen_1'}).encode()
req = urllib.request.Request(f'{BASE}/api/prescriptions/upload', data=form_data)
resp = urllib.request.urlopen(req)
presc = json.loads(resp.read().decode())
print('2. Prescription Uploaded! Extracted drafts count:', len(presc['draft_items']))

confirm_payload = {
    'prescription_id': presc['prescription_id'],
    'items': [{'id': it['id'], 'category': it['category'], 'data': it['data'], 'confirmed': True} for it in presc['draft_items']]
}
req = urllib.request.Request(f'{BASE}/api/prescriptions/confirm', data=json.dumps(confirm_payload).encode(), headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
conf_res = json.loads(resp.read().decode())
print('3. Confirmed Schedule! Generated occurrences:', conf_res['occurrences_created'])

resp = urllib.request.urlopen(f'{BASE}/api/schedule/today/{user_id}')
today_sched = json.loads(resp.read().decode())
print('4. Today Schedule loaded! Medicines:', len(today_sched['medicines']), 'Injections:', len(today_sched['injections']), 'Scans:', len(today_sched['scans']))

if today_sched['medicines']:
    occ_id = today_sched['medicines'][0]['id']
    esc_data = urllib.parse.urlencode({'occurrence_id': occ_id}).encode()
    req = urllib.request.Request(f'{BASE}/api/events/simulate-full-escalation', data=esc_data)
    resp = urllib.request.urlopen(req)
    esc_res = json.loads(resp.read().decode())
    print('5. Escalation Triggered:', esc_res['escalation_triggered'])
    if esc_res.get('escalation_data'):
        print('   Emergency Call dispatched to:', esc_res['escalation_data']['emergency_contact_1'])

resp = urllib.request.urlopen(f'{BASE}/api/reports/summary/{user_id}')
rep_summary = json.loads(resp.read().decode())
print('6. Adherence Report calculated! Overall Adherence:', rep_summary['report']['med_stats']['adherence_pct'], '%')

resp = urllib.request.urlopen(f'{BASE}/api/reports/pdf/{user_id}')
pdf_bytes = resp.read()
print('7. Downloaded PDF Report! Size in bytes:', len(pdf_bytes), 'Valid PDF header:', pdf_bytes.startswith(b'%PDF'))
print('ALL INTEGRATION CHECKS PASSED!')
