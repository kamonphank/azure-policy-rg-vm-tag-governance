# ขั้นตอน deploy Azure Policy ไป Production

เอกสารนี้ใช้คู่กับ [README](../README.md) สำหรับการ deploy จริง ผู้รันต้องมีสิทธิ์สร้างหรือแก้ Policy Definition, Initiative และ Assignment ใน subscription เป้าหมาย การ deploy ชุดนี้ใช้ `Audit` เท่านั้น

## ก่อนวัน deploy

บันทึกรายการต่อไปนี้ใน change record และให้ผู้เกี่ยวข้องตรวจ

- Subscription, scope, branch และ commit ที่จะ deploy
- ค่าใน `config/production.json` ได้แก่ `owner_domain`, `rg_name_patterns`, `allowed_department_values`, `allowed_environment_values`, `excluded_rg_names` และชื่อ assignment
- ผลทดสอบใน Sandbox และผู้รับผิดชอบดูผลหลัง deploy
- วิธีหยุดหรือย้อนการเปลี่ยนแปลงที่ทีมตกลงกัน

`config/production.json` เป็นไฟล์เฉพาะเครื่องและถูก ignore จาก Git อย่า commit ค่าจริง ควร deploy จาก commit ที่ผ่าน review และไม่มีไฟล์โค้ดแก้ค้างอยู่

## 1. ตรวจโดยยังไม่เปลี่ยน Azure

```powershell
python -m unittest discover -s tests -v
python scripts/preflight.py --config config/production.json
python scripts/deploy_all.py --config config/production.json
```

`preflight.py` อ่านข้อมูล Azure เพื่อตรวจ subscription และสิทธิ์อ่าน `deploy_all.py` ที่ไม่มี `--confirm` แสดงแผนอย่างเดียว ไม่เชื่อม Azure ตรวจค่าทุกบรรทัดในแผนก่อนขั้นตอนถัดไป การผ่าน preflight ไม่ได้ยืนยันว่า Azure จะยอมรับ Policy หรือว่ามีสิทธิ์เขียน

## 2. Deploy และตรวจสิ่งที่สร้าง

หลังผ่านขั้นตอน review ของทีมแล้ว ให้รันคำสั่งต่อไปนี้

```powershell
python scripts/deploy_all.py --config config/production.json --confirm
python scripts/verify_deployment.py --config config/production.json
```

สคริปต์ deploy สร้างหรืออัปเดต Policy Definitions 4 ตัว → Initiative → Assignment ที่ระดับ subscription ผล verify ต้องแสดง `Overall: PASS` หากขั้นตอนใดล้มเหลว ให้หยุดและตรวจสิ่งที่ Azure สร้างไปแล้วก่อนรันซ้ำ

## 3. ดูผล compliance

`verify_deployment.py` ตรวจว่า definitions, initiative, assignment และ parameters ถูกสร้างตรง config แต่ไม่ได้ตรวจผล compliance ของ RG/VM ให้ทำตามลำดับด้านล่างหลัง verify ได้ `Overall: PASS`

### 3.1 สั่งสแกน Production subscription

ก่อนเปิดดูผลใน Portal, Resource Graph หรือ Azure CLI ให้รันคำสั่งดังนี้

```powershell
$config = Get-Content config/production.json -Raw | ConvertFrom-Json
$subscriptionId = $config.subscription_id
$assignmentName = if ($config.initiative_assignment_name) { $config.initiative_assignment_name } else { 'rg-tag-governance-audit' }
az policy state trigger-scan --subscription $subscriptionId
```

ถ้า config ไม่มี `initiative_assignment_name` คำสั่งจะใช้ค่าเริ่มต้น `rg-tag-governance-audit` ตรวจว่า subscription และชื่อ assignment ตรงกับผลจากแผน deploy Azure ประเมิน Policy แบบไม่ทันที แม้สั่งสแกนแล้วอาจต้องรอก่อนผลใหม่จะปรากฏ

### 3.2 ดูใน Azure Portal

1. เปิด [Azure Portal](https://portal.azure.com/) ค้นหา **Policy** แล้วเลือก **Compliance**
2. ตั้ง **Scope** เป็น Production subscription จาก `config/production.json` หา assignment ตาม `initiative_assignment_name` (ค่าเริ่มต้น `rg-tag-governance-audit`) แล้วคลิกชื่อ assignment
3. ดู **Resource compliance** เพื่อดู RG/VM และสถานะ `Compliant` หรือ `Non-compliant` คลิก policy ภายใน initiative เพื่อเจาะว่าผิด tag ใด และเปิดรายละเอียดของ resource ที่ไม่ผ่านเพื่อดูเหตุผล
4. เทียบชื่อ RG, resource ID และเวลาประเมินกับสิ่งที่คาดไว้ หากเพิ่งสแกน ผลอาจยังไม่ปรากฏทันที

### 3.3 Query ใน Azure Resource Graph Explorer

ใน Portal ค้นหา **Resource Graph Explorer** เลือก **Directory** แล้วกำหนด scope เป็น Production subscription แทน `<production-subscription-id>` และ `<assignment-name>` ใน KQL ต่อไปนี้ด้วยค่าจาก config (หรือชื่อเริ่มต้นข้างต้น) จากนั้นวาง KQL แล้วกด **Run query**

```kusto
PolicyResources
| where type =~ 'Microsoft.PolicyInsights/PolicyStates'
| extend assignmentId = tostring(properties.policyAssignmentId),
         resourceId = tostring(properties.resourceId),
         policyReference = tostring(properties.policyDefinitionReferenceId),
         complianceState = tostring(properties.complianceState),
         evaluatedAt = todatetime(properties.timestamp)
| where assignmentId =~ '/subscriptions/<production-subscription-id>/providers/Microsoft.Authorization/policyAssignments/<assignment-name>'
| project resourceId, policyReference, complianceState, evaluatedAt
| order by resourceId asc, policyReference asc
```

หนึ่ง resource อาจมีหลายแถว เพราะ initiative มี 4 policies; ใช้ `resourceId` คู่กับ `policyReference` (`require-tag-owner`, `require-tag-department`, `require-tag-environment`, `require-tag-project`) เพื่อระบุว่า tag ใดผ่านหรือไม่ผ่าน หากต้องการดูเฉพาะรายการที่ผิด เพิ่ม `| where complianceState == 'NonCompliant'` ก่อน `project`

### 3.4 ดูด้วย Azure CLI

หลังตั้ง `$subscriptionId` และ `$assignmentName` ตามคำสั่งด้านบน ให้ดึงผลล่าสุดของ assignment ด้วยคำสั่งต่อไปนี้

```powershell
az policy state list `
  --subscription $subscriptionId `
  --policy-assignment $assignmentName `
  --query "[].{Resource:resourceId,Policy:policyDefinitionReferenceId,State:complianceState,Time:timestamp}" `
  --output table
```

ตรวจ `Resource`, `Policy`, `State` และ `Time` รายแถว ผลว่างหลัง deploy ไม่ได้แปลว่าทุก resource ผ่าน ให้ตรวจ scope/assignment แล้วรอผลการประเมินหรือสั่งสแกนซ้ำ RG นอก `rg_name_patterns` หรืออยู่ใน `excluded_rg_names` ไม่ถูกตรวจ tag ตามกติกานี้ แม้ Portal อาจแสดง `Compliant` จากการประเมินเงื่อนไข scope ให้บันทึก resource ID, policy reference, สถานะ และเวลาประเมินไว้ใน change record

ดูข้อมูลเพิ่มเติมได้จาก [การดูผล compliance ใน Portal](https://learn.microsoft.com/en-us/azure/governance/policy/how-to/get-compliance-data), [ตัวอย่าง Azure Resource Graph สำหรับ Policy](https://learn.microsoft.com/en-us/azure/governance/policy/samples/resource-graph-samples) และ [คำสั่ง `az policy state`](https://learn.microsoft.com/en-us/cli/azure/policy/state)

## หากพบปัญหา

หยุด rollout เมื่อพบ subscription หรือ scope ผิด, parameters ผิด, assignment ที่ไม่คาดไว้ หรือผลผิดพลาดที่กระทบการทำงาน แล้วบันทึกปัญหาใน change record Repo นี้ **ไม่มีสคริปต์ rollback อัตโนมัติ** วิธีแก้ต้องเลือกตามสถานการณ์และผู้ดูแลอนุมัติ เช่น คืนค่าของ assignment/definition เดิม หรือ disable/remove assignment อย่าลบ Policy Definitions หรือ Initiative เป็นขั้นแรก เพราะอาจมี assignment อื่นใช้อยู่

## ข้อมูลที่ต้องบันทึก

บันทึก subscription และ assignment, Git commit, ผู้ deploy และเวลา, ผู้ตรวจ config, change reference, ผล tests และ preflight, ผลการ review แผน, ผล deploy และ verify, เวลาสแกนกับผล compliance, ผู้รับผิดชอบติดตามผล รวมถึงปัญหาและสถานะสุดท้าย

การสร้าง VM ตัวอย่างและลบ fixture อยู่ใน [คู่มือ Sandbox](sandbox-testing.md) ส่วนระบบ monitoring, notification, ticket และการเปิด `Deny` ไม่ได้อยู่ในขั้นตอน deploy นี้
