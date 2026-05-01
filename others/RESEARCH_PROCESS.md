# Heir Property Research — Process Overview

**Prepared for:** Trusted Heir Solutions  
**Purpose:** Define what we are searching for, how we search, and what gets stored

---

## What We Are Looking For

The goal is to identify properties where the **original owner is deceased** and the ownership has not been formally transferred to heirs. In many cases, the heirs do not know they have a legal share of the property.

We are specifically looking for:

- **Properties with a deceased owner of record** — still listed under the original owner's name with no recent transfer
- **Delinquent or neglected tax bills** — strong indicator that no living person is actively managing the property
- **Fractional heir interests** — who legally holds a share of the property, including heirs of heirs
- **Heirs who have not yet sold their share** — confirmed through deed records showing no outgoing transfer
- **Contact information for living heirs** — to reach out and offer to purchase their share

---

## The Search Process

### Step 1 — Assessor Search
**Tool:** County Assessor (Wake, Mecklenburg, Buncombe, New Hanover, etc.)  
**Input:** Property address or owner name  
**Purpose:** Establish who the current owner of record is and get the property details

What we capture:
- Owner name as it appears on county records
- Property address and parcel ID
- Last known sale date and sale price
- Assessed/appraised value
- Mailing address (may differ from property — useful for locating owner)

**Signal to watch for:** Owner who purchased decades ago with no updates, no transfers, no recent activity.

---

### Step 2 — Tax Search
**Tool:** County Property Tax  
**Input:** Owner name  
**Purpose:** Check whether taxes are being paid and identify delinquency

What we capture:
- Tax bill history by year
- Payment status (paid / unpaid)
- Outstanding balance
- Property type (real estate, vehicle, business)

**Signal to watch for:** Multiple years of unpaid real estate taxes. This is one of the strongest indicators that the owner is deceased or that heirs are unaware of the property.

---

### Step 3 — Deed Research
**Tool:** County Register of Deeds  
**Input:** Owner name, parcel ID  
**Purpose:** Trace the full ownership chain and identify any prior transfers

What we capture:
- Date and type of every recorded deed on the property
- Grantor (seller/transferor) and grantee (buyer/recipient) for each transaction
- Whether any transfer was from an estate (e.g. "Estate of John Smith") — confirms a prior owner is deceased
- Quitclaim deeds — indicates a family member already transferred or sold their share
- Any partial interest deeds — shows fractional ownership was recorded

**Signal to watch for:** "Estate of [Name]" as grantor means probate occurred. Quitclaim deeds to/from family members show shares have moved informally.

---

### Step 4 — Confirm Owner is Deceased + Identify Heirs
**Tool:** SkipGenie  
**Input:** Deceased owner's full name  
**Purpose:** Build the family tree to identify who legally inherited the property

What we capture:
- Spouse (name, age, last known address)
- Children (names, ages, last known addresses)
- Other known relatives
- Phone numbers for each person identified

**How shares are calculated (NC Intestate Succession — no will):**

| Surviving relatives | How the share is divided |
|---|---|
| Spouse + children | Spouse gets 1/3 · Children split 2/3 equally |
| Children only | Split equally among all children |
| No spouse or children | Parents first, then siblings |

If a child or heir is also deceased, their share passes to *their* heirs. This is how a single property can end up with 10–20 living claimants across multiple generations.

---

### Step 5 — Cross-Check Heirs Against Deed Records
**Tool:** County Register of Deeds  
**Input:** Each heir's name  
**Purpose:** Confirm which heirs still hold their share and which have already sold

What we are checking:
- Has this heir recorded a deed transferring their interest out? (if yes, they no longer have a share)
- Has this heir received a deed transferring additional interest in? (increases their share)
- Are there any recorded agreements or liens against their interest?

---

### Step 6 — Contact Living Heirs
**Source:** SkipGenie contact info + deed mailing addresses  
**Purpose:** Reach out to heirs who still hold a share and offer to purchase it

---

## What Gets Captured Into the Database and Documents

### Per Property Record
| Field | Source |
|---|---|
| Parcel ID | Assessor |
| Property address | Assessor |
| County | Assessor |
| Assessed value | Assessor |
| Last recorded owner | Assessor |
| Last sale date | Assessor |
| Last sale price | Assessor |
| Tax status (current / delinquent) | Tax records |
| Years of unpaid taxes | Tax records |
| Outstanding tax balance | Tax records |
| Deed chain summary | Register of Deeds |
| Estate transfer recorded (Y/N) | Register of Deeds |
| Date of estate transfer | Register of Deeds |

### Per Heir Record
| Field | Source |
|---|---|
| Full name | SkipGenie / Deeds |
| Relationship to deceased owner | Research |
| Estimated share (fraction) | Intestate calculation |
| Last known address | SkipGenie |
| Phone number(s) | SkipGenie |
| Has existing deed transfer out (Y/N) | Register of Deeds |
| Contact attempted (Y/N) | Internal |
| Status (interested / not interested / unreachable) | Internal |

### Per Research Case
| Field | Notes |
|---|---|
| Case opened date | |
| Original deceased owner | |
| Date of death (if known) | |
| Total number of identified heirs | |
| Number of heirs still holding shares | |
| Number of shares acquired | |
| Case status | Active / Closed / On hold |
| Notes | Anything that doesn't fit a structured field |

---

## Summary

```
Property address or owner name
        ↓
Assessor → confirm ownership, get parcel ID + value
        ↓
Tax records → check for delinquency (deceased signal)
        ↓
Deeds → trace ownership chain, find estate transfers
        ↓
Owner confirmed deceased
        ↓
SkipGenie → identify family members (potential heirs)
        ↓
Calculate shares using intestate succession rules
        ↓
Deeds (again) → confirm which heirs haven't sold yet
        ↓
Contact living heirs → offer to purchase their share
```
