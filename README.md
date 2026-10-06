# Azure Policy สำหรับตรวจ tags ของ RG และ VM

โปรเจกต์นี้สร้าง Azure Policy 4 ตัว แล้วรวมเป็น Initiative เดียวเพื่อตรวจ tags ของ Resource Group (RG) และ Virtual Machine (VM) เริ่มใช้งานด้วย `Audit`: รายงานสิ่งที่ไม่ตรงกติกาโดยยังไม่ปฏิเสธการสร้าง resource

## ตรวจอะไรบ้าง

| Tag | กติกา |
| --- | --- |
| `owner` | ใส่อีเมลได้หลายค่า คั่นด้วย comma ทุกค่าต้องใช้โดเมนตัวพิมพ์เล็กตาม `owner_domain` |
| `department` | ต้องตรงกับหนึ่งใน `allowed_department_values` รวมตัวพิมพ์เล็กใหญ่ |
| `environment` | ค่าเริ่มต้นคือ `Production`, `Development`, `Test` หรือ `Sandbox` |
| `project` | ใส่หลายค่าได้โดยคั่นด้วย comma และไม่มีช่องว่างติด comma |

Policy ถูก assign ที่ระดับ subscription แต่ตรวจเฉพาะ RG ที่ชื่อเข้ากับ `rg_name_patterns` และ VM ภายใน RG เหล่านั้น VM ต้องมี tags ของตัวเอง; ไม่ได้สืบทอด tags จาก RG

รูปแบบชื่อใช้ `#` แทนตัวเลขหนึ่งตัว และ `?` แทนตัวอักษรหนึ่งตัว เช่น pattern ตัวอย่าง `R###RG??##` ใช้ `excluded_rg_names` เพื่อยกเว้น RG ที่ปกติอยู่ในขอบเขต รวมทั้ง VM ภายใน

## เริ่มใช้งาน

### 1. เตรียมเครื่อง

```powershell
git clone <repository-url>
cd azure-policy-rg-tag-governance
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. เตรียม config

```powershell
Copy-Item config/production.example.json config/production.json
```

แก้ `config/production.json` ให้ตรงกับ subscription ที่จะใช้ โดยต้องกำหนดค่าต่อไปนี้

| ค่า | ความหมาย |
| --- | --- |
| `subscription_id` | Subscription เป้าหมาย |
| `owner_domain` | โดเมนอีเมลที่ยอมรับ เช่น `example.com` |
| `rg_name_patterns` | รายการรูปแบบชื่อ RG ที่ต้องตรวจ |
| `allowed_department_values` | รายชื่อแผนกที่ยอมรับ |

ตัวอย่างใน repo เป็นค่าทั่วไป **ต้องตรวจและเปลี่ยนก่อน deploy** ไฟล์ `config/production.json` ถูก ignore จาก Git; อย่า commit ค่าจริงลง repo `effect` ของขั้นตอน deploy นี้ต้องเป็น `Audit`

### 3. ตรวจโค้ดและแผน

```powershell
python -m unittest discover -s tests -v
python scripts/preflight.py --config config/production.json
python scripts/deploy_all.py --config config/production.json
```

`preflight.py` อ่านข้อมูล Azure เพื่อตรวจ subscription และสิทธิ์อ่าน ส่วน `deploy_all.py` ที่ไม่มี `--confirm` แสดงแผนโดย **ไม่เชื่อม Azure และไม่ deploy** ตรวจค่าที่แสดงทุกครั้ง Tests ในเครื่องช่วยจับการเปลี่ยนกติกา แต่ยังต้องทดสอบกับ Azure จริงใน Sandbox

### 4. Deploy และตรวจผล

เมื่อผ่านการ review ตามขั้นตอนของทีมแล้ว ให้ทำตาม [คู่มือ Production](docs/production-deployment-runbook.md) และรันคำสั่งต่อไปนี้

```powershell
python scripts/deploy_all.py --config config/production.json --confirm
python scripts/verify_deployment.py --config config/production.json
```

สคริปต์ deploy เรียงจาก Policy Definitions ทั้ง 4 ตัว → Initiative → Assignment คำสั่ง verify ต้องแสดง `Overall: PASS` หลังจากนั้น Azure จะประเมิน compliance แบบไม่ทันที หากต้องการเร่งให้สแกน ให้รันคำสั่งต่อไปนี้

```powershell
az policy state trigger-scan --subscription <subscription-id>
```

อ่านผลโดยดู `resourceId` คู่กับ `policyDefinitionReferenceId` เพราะ RG และ VM ใช้ assignment เดียวกัน RG นอกขอบเขตอาจปรากฏเป็น `Compliant` ใน Portal ซึ่งไม่ได้แปลว่า tags ของ RG นั้นถูกตรวจแล้ว

## เอกสารอื่น

- [สรุปการออกแบบ](docs/technical-design.md) — scope, กติกา และข้อจำกัดของ Policy
- [คู่มือทดสอบ Sandbox](docs/sandbox-testing.md) — สร้าง VM ตัวอย่าง ตรวจผล และลบ fixture
- [คู่มือ deploy Production](docs/production-deployment-runbook.md) — ลำดับตรวจและบันทึกผล

## สิ่งที่ยังไม่ทำ

- ยังไม่มี automatic remediation, monitoring, notification หรือ ticket workflow
- ยังไม่ตรวจว่า mailbox ของ `owner` มีอยู่จริง
- ยังไม่รวม VM scale sets, VM extensions, Arc machines และ resource type อื่น
- RG ที่ชื่อไม่เข้ากับ `rg_name_patterns` จะไม่ถูกตรวจ tags
