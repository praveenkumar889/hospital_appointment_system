---
name: healthcare-testing
description: Standardized testing workflow for healthcare appointment booking applications, enforcing PII safety, double-booking prevention, and transaction integrity.
---

# Healthcare Testing Skill

## When to Use

Use this skill when:
- Building appointment-related features
- Implementing patient data handling
- Creating healthcare workflows
- Adding doctor/hospital management features

## Critical Healthcare Test Requirements

Every test must verify:

1. **No Patient PII in Logs**
   - Verify patient phone numbers, names, or emails are never printed in log files.

2. **Double-Booking Prevention**
   - Verify two concurrent requests cannot reserve the same slot for the same doctor.

3. **Doctor Availability Constraints**
   - Verify appointments cannot be booked for non-existent or inactive time slots.

4. **Transaction Integrity**
   - Appointment record insertion and slot availability update must be atomic.

5. **Appointment Status Validation**
   - Enforce valid state transitions (`booked` -> `rescheduled` / `cancelled`).
