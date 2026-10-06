# สรุปการออกแบบ Azure Policy

เอกสารนี้อธิบายกติกาที่โค้ดปัจจุบันทำจริง สำหรับวิธีรันให้เริ่มที่ [README](../README.md)

## โครงสร้าง

```text
Subscription
  └─ Assignment: rg-tag-governance-audit
      └─ Initiative: rg-tag-governance-initiative
          ├─ require-tag-owner
          ├─ require-tag-department
          ├─ require-tag-environment
          └─ require-tag-project
```

Policy Definitions ทั้ง 4 ตัวใช้ `mode: All` และตรวจ `Microsoft.Resources/subscriptions/resourceGroups` กับ `Microsoft.Compute/virtualMachines` เท่านั้น ตอน deploy สคริปต์สร้างหรืออัปเดต definitions ก่อน แล้วจึงสร้าง Initiative และ Assignment

## Resource ใดอยู่ในขอบเขต

RG จะถูกตรวจเมื่อชื่อเข้ากับ pattern อย่างน้อยหนึ่งค่าใน `rg_name_patterns` และไม่อยู่ใน `excluded_rg_names` สำหรับ VM จะใช้ชื่อ RG ที่ VM อยู่เพื่อตัดสินขอบเขต ไม่ใช้ชื่อ VM การยกเว้น RG จึงครอบคลุม VM ภายในด้วย

ตัวอย่างทั่วไป: `R###RG??##` โดย `#` แทนตัวเลข และ `?` แทนตัวอักษร ค่าใช้งานจริงอ่านจาก config ที่ไม่ commit หาก RG ที่ควรถูกกำกับดูแลมีชื่อไม่เข้า pattern ระบบจะไม่ตรวจ tags ของ RG และ VM ภายใน

VM ใช้ tags บน VM เอง ไม่มีการคัดลอก tags จาก RG ใน expression ที่ต้องอ้างชื่อ RG แม่ มี `if` ให้เรียก `resourceGroup()` เฉพาะเมื่อ resource เป็น VM

## กติกาของ tags

### `owner`

ต้องมีอย่างน้อยหนึ่งอีเมล หลายค่าคั่นด้วย comma โดยไม่มีช่องว่างรอบ comma แต่ละค่าต้องมีข้อความก่อน `@`, มี `@` เพียงตัวเดียว และใช้โดเมนตัวพิมพ์เล็กที่กำหนดใน `owner_domain` เช่น หากตั้ง `example.com` ค่า `alice@example.com,bob@example.com` ผ่าน แต่ `alice@EXAMPLE.COM`, `alice@exampleXcom`, subdomain และโดเมนอื่นไม่ผ่าน

Policy ปฏิเสธค่าที่ว่าง มี comma ซ้อนกัน มี comma หน้า/ท้าย หรือมี space, tab, CR, LF ใน tag การตรวจแต่ละรายการใช้ value `count` ที่วนได้สูงสุด 100 ค่า และมีเงื่อนไขแยกสำหรับค่าที่เกิน 100 เพื่อไม่ให้การประเมินเกินข้อจำกัดของ Azure กติกานี้ **ไม่ตรวจว่า mailbox มีอยู่จริง** และไม่ตรวจรูปแบบอีเมลตาม RFC ทั้งหมด

### `department`

ต้องมีค่าและตรงกับหนึ่งใน `allowed_department_values` รวมตัวพิมพ์เล็กใหญ่ รายการจริงมาจาก config; ค่าในไฟล์ example มีไว้แสดงรูปแบบเท่านั้น

### `environment`

ต้องมีค่าและตรงกับ `allowed_environment_values` รวมตัวพิมพ์เล็กใหญ่ ค่าเริ่มต้นคือ `Production`, `Development`, `Test`, `Sandbox`

### `project`

ต้องมีค่า ใส่หลายชื่อได้โดยคั่นด้วย comma ช่องว่างภายในชื่ออนุญาต แต่ช่องว่างติด comma ไม่ผ่าน เช่น `Project Alpha,Project Beta` ผ่าน ส่วน `Project Alpha, Project Beta` และ `ProjectA,,ProjectB` ไม่ผ่าน

## ค่าที่ส่งจาก config ไป Azure

| ใน config | Parameter ของ Initiative | ส่งต่อไปยัง Policy |
| --- | --- | --- |
| `effect` | `effect` | ทั้ง 4 ตัว |
| `excluded_rg_names` | `excludedRGNames` | ทั้ง 4 ตัว |
| `rg_name_patterns` | `rgNamePatterns` | ทั้ง 4 ตัว |
| `owner_domain` | `ownerDomain` | `owner` |
| `allowed_department_values` | `allowedDepartmentValues` | `department` |
| `allowed_environment_values` | `allowedEnvironmentValues` | `environment` |

`owner_domain`, `rg_name_patterns` และ `allowed_department_values` เป็นค่าที่ต้องมีใน config สคริปต์จะหยุดก่อน deploy หากขาดค่า `effect` สำหรับการ deploy ผ่านโปรเจกต์นี้ต้องเป็น `Audit` แม้ JSON ของ Policy รองรับ effect อื่น

## การทดสอบและข้อจำกัด

สคริปต์ Python ใช้ Azure SDK และ `DefaultAzureCredential` คำสั่ง `deploy_all.py` ที่ไม่มี `--confirm` เป็นการแสดงแผนในเครื่อง ส่วน `preflight.py` อ่านข้อมูล Azure และ `verify_deployment.py` ตรวจสิ่งที่ deploy แล้ว

Tests ใน `tests/` อ่าน Policy JSON จริงเพื่อจับข้อผิดพลาดของกติกา แต่ยังไม่แทน Azure Policy engine ต้องยืนยันผลบน Sandbox โดยดู `resourceId`, `policyDefinitionReferenceId`, ค่า assignment และเวลาที่ Azure ประเมินผล ดูวิธีใน [คู่มือ Sandbox](sandbox-testing.md)

ยังไม่มีการแก้ tags อัตโนมัติหรือระบบแจ้งเตือน และยังไม่ตรวจ resource type อื่นนอกเหนือจาก RG กับ VM ข้อกำหนดของ syntax และข้อจำกัด value `count` ดูได้ที่ [Microsoft Learn](https://learn.microsoft.com/en-us/azure/governance/policy/concepts/definition-structure-policy-rule)
