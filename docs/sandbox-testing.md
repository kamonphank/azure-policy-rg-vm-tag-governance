# ทดสอบ Policy ใน Sandbox

ใช้คู่มือนี้เมื่อต้องการเห็นผลจาก Azure Policy จริง เช่น VM ใช้ tags ของตัวเองหรือ RG ที่ถูกยกเว้นไม่ถูกตรวจ ขั้นตอนสร้าง VM และอุปกรณ์เครือข่ายใน subscription ทดสอบ จึงอาจมีค่าใช้จ่าย

## 1. ตรวจ config

ใช้ `config/sandbox.json` ที่ไม่ commit ตรวจ `subscription_id`, `location`, `owner_domain`, `allowed_department_values` และ `rg_name_patterns` ให้ถูกต้อง **ชุด fixture ในสคริปต์นี้ต้องมี `R###RG??##` ใน `rg_name_patterns`** เพราะชื่อ RG ตัวอย่างขึ้นต้นด้วย `R901RGAA` หากไม่ต้องการเพิ่ม pattern นี้ใน Sandbox ปัจจุบัน ให้ทดสอบ Policy ด้วย resource ของคุณเองแทน

ก่อนสร้าง VM ให้รัน tests และดูแผนด้วยคำสั่งต่อไปนี้

```powershell
python -m unittest discover -s tests -v
python scripts/deploy_all.py --config config/sandbox.json
```

## 2. Deploy Policy และสร้าง VM ตัวอย่าง

การรัน fixture ครั้งแรกจะ deploy Policy Definitions, Initiative และ Assignment ก่อนสร้าง VM จากนั้น VM จะถูก deallocate แต่ managed disk ยังอาจมีค่าใช้จ่าย ต้องมี SSH public key และเลือก VM size/zone ที่ region รองรับ

```powershell
python scripts/create_vm_tag_test_fixtures.py `
  --fixture R901RGAA01/vm-valid-01 `
  --vm-size <available-x64-size> `
  --zone <available-zone>
```

หาก Policy ถูก deploy แล้ว รอบถัดไปให้ใช้ `--skip-policy-deploy` เพื่อสร้างเฉพาะ fixture ตามตัวอย่างนี้

```powershell
python scripts/create_vm_tag_test_fixtures.py `
  --fixture R901RGAA02/vm-missing-tags `
  --vm-size <available-x64-size> `
  --zone <available-zone> `
  --skip-policy-deploy
```

| Fixture | สิ่งที่ทดสอบ |
| --- | --- |
| `R901RGAA01/vm-valid-01` | RG และ VM มี tags ถูกต้อง |
| `R901RGAA02/vm-missing-tags` | VM ขาด tags |
| `R901RGAA03/vm-valid-tags` | RG ขาด tags แต่ VM มีครบ |
| `R901RGAA04/vm-owner`, `vm-department`, `vm-environment`, `vm-project` | VM ผิดกติกาทีละ tag |
| `R901RGAA05/vm-owner-domain`, `R901RGAA06/vm-owner-format` | ใช้เปลี่ยนค่า owner แล้วสแกนซ้ำ |
| `unmanaged-rg/R901RGAA99` | ชื่อ VM อย่างเดียวไม่ทำให้ RG เข้า scope |
| `R901RGAA08/vm-excluded` | ทดสอบ `excluded_rg_names` |

ถ้า subscription มี quota จำกัด ให้สร้างและลบทีละ VM

## 3. ตรวจผล Azure

หลังสร้าง resource ให้เริ่มสแกนและรอผลประเมินด้วยคำสั่งต่อไปนี้

```powershell
az policy state trigger-scan --subscription <subscription-id>
az policy state list `
  --subscription <subscription-id> `
  --policy-assignment rg-tag-governance-audit `
  --query "[].{Resource:resourceId,State:complianceState,Policy:policyDefinitionReferenceId,Time:timestamp}" `
  -o table
```

ดู `resourceId` คู่กับ `policyDefinitionReferenceId` อย่าใช้ชื่อ RG เพียงอย่างเดียว เพราะ RG และ VM อยู่ภายใต้ assignment เดียวกัน

## 4. ลบ fixture

หากต้องการลบ VM ตัวเดียวพร้อม managed OS disk ให้ใช้คำสั่งนี้

```powershell
python scripts/cleanup_vm_tag_test_fixtures.py `
  --vm R901RGAA01/vm-valid-01 `
  --confirm
```

หากจะลบ RG fixture ทั้งชุด ให้ **รันโดยไม่มี `--confirm` ก่อน** จากนั้นตรวจ `subscription_id` ใน config และรายชื่อ RG ที่สคริปต์แสดง แล้วจึงรันแบบยืนยันตามตัวอย่างนี้

```powershell
python scripts/cleanup_vm_tag_test_fixtures.py --config config/sandbox.json
python scripts/cleanup_vm_tag_test_fixtures.py --config config/sandbox.json --confirm
```

ถ้ามี fixture ชื่อเก่าที่ต่างจากตาราง ให้ใส่ชื่อ RG ที่ต้องลบลงใน `fixture_resource_group_names` ของ `config/sandbox.json` แล้วตรวจรายการจากคำสั่งแรกอีกครั้ง การลบ Policy Definitions, Initiative และ Assignment ต้องระบุ `--delete-policy` เพิ่ม และควรทำเฉพาะเมื่อยืนยันว่าไม่มีงานอื่นใช้ Policy ชุดนี้
