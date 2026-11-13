# Durable agents hackathon: 100 problems

AI Yatra · 14 Nov 2026 · after the "Durable AI Agents" talk.

Also as a spreadsheet: [problems.csv](problems.csv).

Every problem is a real job from someone's day. Pick one, build an agent for it, and show it **surviving a kill -9** live.

## The rules

- **Use anything.** Temporal (free local dev server: `temporal server start-dev`, or the Docker image), LangGraph with `SqliteSaver` / Postgres, DBOS, Restate, Inngest, or your own Postgres table. No paid accounts needed.
- **Mock the outside world.** Banks, SMS, couriers and government portals are mocks. [`shop_mock.py`](../shop_mock.py) from the talk is a fine starting point.
- **The LLM is optional.** A mock is fine and makes crashes repeatable. For a real one, NVIDIA's free endpoint or Ollama.
- **Long waits are compressed.** 1 day = 1 minute. Say so in your demo.
- **The demo.** Show the counter (payments, SMS, tickets) before and after. Kill the process where the problem says. Restart, or let your engine restart it. The rule under "must hold" must hold.

**Promises** (from the talk): **resume** from the exact step · side effects happen **once** · **wait** hours or days for a person or a timer · **written down**: every step recorded.

**Levels:** Beginner = one flow, one promise · Intermediate = a full flow with a wait · Advanced = many items, workers or approvals.

## Judging

| | |
|---|---|
| Survives the kill, live | 40% |
| The counters are right after the crash | 25% |
| It's a real problem, solved | 20% |
| Clear demo in 5 minutes | 15% |


## 1. Payments & money

### P001 · Split the dinner bill

*Beginner · once · wait*

Six friends ate out; one paid ₹4,800. Chasing the other five on WhatsApp is awkward and someone always forgets.

- **Build:** An agent that splits the bill, sends each friend a UPI collect request and reminds them once a day until they pay.
- **Kill test:** Kill it after 3 of the 5 requests are sent.
- **Must hold:** Every friend gets exactly one request. Reminders carry on from where they were.

### P002 · Rent day at a PG

*Beginner · once · resume*

A PG owner collects rent from 40 tenants on the 5th of every month, by hand, from a notebook.

- **Build:** An agent that charges every tenant, sends a receipt and marks the month paid.
- **Kill test:** Kill it halfway down the tenant list.
- **Must hold:** 40 charges, 40 receipts. Nobody is charged twice, nobody is skipped.

### P003 · Salary day at a 30-person startup

*Intermediate · once · resume · written down*

Payroll runs as one bulk bank transfer plus 30 payslip emails. If it dies halfway, finance has to work out who got paid.

- **Build:** A payroll agent: compute pay, transfer, email payslips, write a payroll register.
- **Kill test:** Kill it after the bank accepted the transfers but before the payslips go out.
- **Must hold:** Each person paid once and gets one payslip. The register shows every step.

### P004 · Money debited, not received

*Intermediate · wait · once*

A customer's UPI payment is debited, but the shop never got it. The bank settles it by T+1: reversed or success.

- **Build:** A support agent that checks the payment status, waits for the bank, then either confirms the order or tells the customer it reversed.
- **Kill test:** Kill it while it waits for the bank. Restart it.
- **Must hold:** It comes back still waiting. It never refunds money that's still pending.

### P005 · EMI bounce handler

*Intermediate · wait · resume · written down*

An NBFC's EMI auto-debit bounced. Rules say: retry on the 10th and 15th, notify the customer, hand over to a collections officer after 3 failures.

- **Build:** An agent that runs that schedule for each loan.
- **Kill test:** Kill it between two retries, and once again right after a retry.
- **Must hold:** Retries happen only on the scheduled dates, never because the agent restarted.

### P006 · Monthly chit fund

*Intermediate · once · written down*

A 20-member chit fund collects every month, draws a winner and pays out. Members argue when the draw looks redone.

- **Build:** An agent that collects, draws, pays out and publishes the result.
- **Kill test:** Kill it after the draw and before the payout.
- **Must hold:** The winner never changes on restart. One payout per month.

### P007 · Bank credits vs invoices

*Advanced · resume · wait · written down*

A shop gets 500 bank credits a day and has to match each to an invoice for GST. Narrations are messy.

- **Build:** An agent that matches credits to invoices (LLM for the fuzzy ones) and sends unclear ones to the accountant to confirm.
- **Kill test:** Kill it mid-batch, and again while the accountant is reviewing.
- **Must hold:** Each credit matched once. Pending reviews survive. Paid-for LLM calls aren't repeated.

### P008 · Refund desk with limits

*Intermediate · once · wait · written down*

An online store: refunds up to ₹2,000 are automatic, above that a manager approves, and managers take days.

- **Build:** A refund agent with that rule.
- **Kill test:** Kill it while it waits for the manager, then again right after the refund call.
- **Must hold:** One refund per order. The approval wait survives restarts.

### P009 · Festival cashback

*Beginner · once · resume*

Diwali offer: the first 1,000 UPI payments above ₹500 get ₹50 cashback.

- **Build:** An agent that watches payments and pays the cashback.
- **Kill test:** Kill it around payment 600.
- **Must hold:** Exactly 1,000 cashbacks. Nobody gets two.

### P010 · Expense claims

*Beginner · wait · once*

Employees upload bills; a manager approves; finance pays. Claims get lost in email.

- **Build:** An agent that reads the bill, fills the claim, waits for the manager, then pays.
- **Kill test:** Kill it while the claim waits for approval.
- **Must hold:** The claim is still waiting after the restart. Paid once.


## 2. Food & retail

### P011 · Chai shop, plus delivery

*Beginner · once · resume*

The chai agent from the talk now also books a delivery rider.

- **Build:** Start from this repo and add a book_rider step.
- **Kill test:** Kill it after the charge, and again after the rider is booked.
- **Must hold:** Payments 1, kitchen tickets 1, riders 1.

### P012 · Cloud kitchen router

*Intermediate · once · resume*

Orders arrive on WhatsApp. Three kitchens, different stock. Whichever has it cooks it; then a rider is booked.

- **Build:** An agent that checks stock, routes the order, books a rider.
- **Kill test:** Kill it after a kitchen accepted and before the rider is booked.
- **Must hold:** One kitchen cooks, one rider comes.

### P013 · Sold out after payment

*Intermediate · wait · once*

The customer paid, then the item ran out. Do you refund, wait or swap?

- **Build:** An agent that asks the customer (wait / swap / refund) and refunds by default after 30 minutes.
- **Kill test:** Kill it while it waits for the customer.
- **Must hold:** Still waiting after restart. The timeout still fires on time. One refund at most.

### P014 · Kirana restock

*Beginner · wait · once*

A kirana owner photographs empty shelves at night. The distributor takes orders in the morning.

- **Build:** An agent that drafts the order from the photo and sends it once the owner says yes.
- **Kill test:** Kill it overnight while it waits for the owner.
- **Must hold:** One order to the distributor, only after a yes.

### P015 · 300 Diwali hampers

*Intermediate · resume · once · written down*

A company sends hampers to 300 employees' homes.

- **Build:** An agent that books 300 shipments and reports what went out.
- **Kill test:** Kill it around shipment 150.
- **Must hold:** 300 shipments, none doubled, a report of all 300.

### P016 · Table booking with a deposit

*Beginner · wait · once*

A restaurant takes ₹500 deposits, reminds guests 2 hours before, and releases no-show tables.

- **Build:** An agent that books, charges the deposit, reminds and releases.
- **Kill test:** Kill it between the booking and the reminder.
- **Must hold:** The reminder still goes out on time, once.

### P017 · Abandoned cart

*Beginner · wait · once*

A D2C brand sends 3 reminders over 3 days to people who left items in the cart.

- **Build:** An agent that sends them and stops the moment the customer buys.
- **Kill test:** Kill it between reminders.
- **Must hold:** No reminder twice. None after a purchase.

### P018 · Returns and refunds

*Intermediate · wait · once · written down*

A return goes: book pickup, item reaches the warehouse, QC takes 2–3 days, then refund or reject.

- **Build:** An agent that runs that flow per return.
- **Kill test:** Kill it while it waits for QC.
- **Must hold:** Still waiting after restart. Refund once, only after QC passes.

### P019 · Flash sale: 100 units

*Advanced · once · resume*

100 units, 10,000 buyers in a minute. Reservations expire if not paid in 10 minutes.

- **Build:** An agent (or several workers) that reserves, charges and confirms.
- **Kill test:** Kill workers at random during the sale.
- **Must hold:** Never sell 101. Nobody is charged without an order.

### P020 · Price update everywhere

*Intermediate · resume · once · written down*

A restaurant changes prices. They must change on two delivery apps and its own website.

- **Build:** An agent that updates all three (mock them) and logs who changed what.
- **Kill test:** Kill it after the first app is updated.
- **Must hold:** All three updated, each once. The log shows every change.


## 3. Travel & bookings

### P021 · Tatkal at 10:00

*Intermediate · wait · once*

Tatkal opens at 10:00 sharp. Miss it and the seats are gone.

- **Build:** An agent that waits until 10:00, books, pays and sends the ticket (mock the booking site).
- **Kill test:** Kill it at 09:59. Kill it again after payment.
- **Must hold:** It still books at 10:00. One ticket, one payment.

### P022 · Group trip: all or nothing

*Intermediate · resume · once*

Eight friends need a train, a hotel and a cab. If the hotel fails, the train should be cancelled too.

- **Build:** An agent that books all three and undoes what it booked if one fails.
- **Kill test:** Kill it after the train is booked and before the hotel.
- **Must hold:** Either everything is booked or everything is cancelled. Nothing paid twice.

### P023 · Flight cancelled: rebook 50 people

*Advanced · resume · wait · once*

A flight is cancelled. 50 passengers need a new flight or a hotel, and each one chooses.

- **Build:** An agent that offers options to each passenger, waits for replies and books.
- **Kill test:** Kill it halfway through the passengers.
- **Must hold:** Each passenger rebooked once. Pending replies still pending.

### P024 · Hotel pre-check-in

*Beginner · resume · wait*

A hotel collects ID, payment and preferences over WhatsApp before arrival. Guests reply hours apart.

- **Build:** A chat agent that collects it all across days.
- **Kill test:** Kill it mid-conversation.
- **Must hold:** It never asks a question the guest already answered.

### P025 · Visa tracker

*Intermediate · wait · written down*

A visa: fill the form, book a slot, wait weeks for a decision, send documents when asked.

- **Build:** An agent that tracks one application end to end.
- **Kill test:** Kill it during the weeks-long wait (1 day = 1 minute).
- **Must hold:** Still waiting. The history shows every step.

### P026 · Hold a bus seat for 10 minutes

*Beginner · wait · once*

A seat is held while the customer pays. If they don't, it goes back on sale.

- **Build:** An agent with a 10-minute hold.
- **Kill test:** Kill it during the hold.
- **Must hold:** The seat is either sold once or released once.

### P027 · Darshan slots for a family

*Intermediate · once · resume*

Temple darshan slots open monthly and sell out in minutes. A family of six needs them together.

- **Build:** An agent that books six slots, pays and sends the tickets.
- **Kill test:** Kill it after payment.
- **Must hold:** One payment, six tickets.

### P028 · 4 AM airport cab

*Beginner · wait · resume*

Booked the night before. At 3:30 the driver has to confirm or someone has to find another.

- **Build:** An agent that schedules the cab, checks at 3:30 and escalates if there's no driver.
- **Kill test:** Kill it at midnight.
- **Must hold:** The 3:30 check still happens.

### P029 · Cancelled trip: three refunds

*Intermediate · wait · once · written down*

Airline, hotel and cab each refund on their own timeline: days to weeks.

- **Build:** An agent that requests all three and follows up until each arrives.
- **Kill test:** Kill it while it waits.
- **Must hold:** Each refund requested once. The log shows which arrived when.

### P030 · Corporate travel approval

*Intermediate · wait · once · written down*

Manager approves every trip; finance also approves above ₹50,000; then it's booked.

- **Build:** An agent that runs the approvals and books.
- **Kill test:** Kill it between the two approvals.
- **Must hold:** Approvals aren't asked again. Booked once.


## 4. Healthcare

### P031 · Clinic appointments

*Beginner · wait · once*

A clinic books slots, reminds patients a day before and marks no-shows.

- **Build:** An agent that does all three.
- **Kill test:** Kill it between the booking and the reminder.
- **Must hold:** One reminder, on time.

### P032 · Lab report follow-up

*Intermediate · wait · written down*

A blood sample takes hours to days. Critical values must reach the doctor fast.

- **Build:** An agent that waits for the lab, sends the report and alerts the doctor for critical values.
- **Kill test:** Kill it while it waits for the lab.
- **Must hold:** The report is sent once. Critical alerts are never missed.

### P033 · Monthly medicine refill

*Intermediate · wait · once*

A diabetic patient needs the same medicines every month. Some need a pharmacist's approval.

- **Build:** An agent that checks stock, waits for the pharmacist, charges and delivers.
- **Kill test:** Kill it while it waits for the pharmacist.
- **Must hold:** Charged once, delivered once.

### P034 · Hospital discharge

*Advanced · resume · wait · written down*

Discharge needs billing, pharmacy and insurance. Insurance approval takes hours.

- **Build:** An agent that coordinates the three and tells the family where things stand.
- **Kill test:** Kill it while insurance is pending.
- **Must hold:** No department is asked twice. The family sees the true status.

### P035 · Insurance claim

*Advanced · wait · written down · resume*

A health claim: submit documents, answer queries over weeks, get settled.

- **Build:** An agent that runs one claim end to end.
- **Kill test:** Kill it during a query wait.
- **Must hold:** Resumes at the open query. Full history of the claim.

### P036 · Blood donation drive

*Beginner · once · resume*

500 donors to message, slots to book, reminders to send.

- **Build:** An agent that does it.
- **Kill test:** Kill it around donor 250.
- **Must hold:** Each donor messaged once.

### P037 · Newborn vaccination schedule

*Beginner · wait*

Vaccines are due over 18 months. Parents forget.

- **Build:** An agent that reminds parents on each due date.
- **Kill test:** Kill it, then restart it 'three months later' (1 month = 1 minute).
- **Must hold:** The next reminder is the right one, on the right date.

### P038 · Ambulance dispatch

*Intermediate · wait · written down · once*

An ambulance is assigned; if the driver doesn't accept in 2 minutes, reassign.

- **Build:** A dispatch agent with a full log.
- **Kill test:** Kill it while it waits for the driver.
- **Must hold:** One ambulance per call. Every assignment logged.

### P039 · Doctor-approved medicine order

*Intermediate · wait · once*

Some orders need the doctor to say yes on their phone first.

- **Build:** An agent that drafts the order, waits for the doctor, then orders.
- **Kill test:** Kill it while it waits.
- **Must hold:** Ordered once, only after a yes.

### P040 · Teleconsult follow-up

*Beginner · wait · once*

After a video consult: send the prescription, book a follow-up in 7 days.

- **Build:** An agent that does both.
- **Kill test:** Kill it right after the consult ends.
- **Must hold:** One prescription, one follow-up.


## 5. Government & paperwork

### P041 · Monthly GST filing

*Intermediate · once · wait · written down*

Collect invoices all month, prepare the return, the CA approves, file before the 20th.

- **Build:** An agent that runs the month (mock the GST portal).
- **Kill test:** Kill it after filing and before the acknowledgement is saved.
- **Must hold:** Filed once. The acknowledgement is recovered, not refiled.

### P042 · KYC onboarding

*Intermediate · resume · wait · written down*

PAN, Aadhaar, a video KYC slot, then an officer verifies.

- **Build:** An agent that runs KYC for one customer (mock everything).
- **Kill test:** Kill it between the video slot and the officer's check.
- **Must hold:** No step redone. The officer's decision is recorded.

### P043 · Passport appointment watcher

*Beginner · wait*

Appointment slots open at random times.

- **Build:** An agent that checks every hour and books the first slot.
- **Kill test:** Kill it, restart it.
- **Must hold:** Checks continue on schedule. One booking.

### P044 · Property tax for a society

*Beginner · once · resume*

120 flats; the society pays each flat's property tax and collects receipts.

- **Build:** An agent that pays all 120.
- **Kill test:** Kill it around flat 60.
- **Must hold:** 120 payments, 120 receipts.

### P045 · RTI tracker

*Beginner · wait · written down*

An RTI must be answered in 30 days; if not, file a first appeal.

- **Build:** An agent that files, waits and appeals.
- **Kill test:** Kill it on 'day 20'.
- **Must hold:** The appeal is filed on day 31, once.

### P046 · Compliance calendar

*Intermediate · wait · written down*

TDS, ROC and GST deadlines. A director has to sign some of them.

- **Build:** An agent that prepares each filing, reminds, and waits for the signature.
- **Kill test:** Kill it while it waits for a signature.
- **Must hold:** No deadline missed. The log shows who signed when.

### P047 · Electricity bill dispute

*Beginner · wait · written down*

A wrong bill. The complaint needs follow-up every week until it's fixed.

- **Build:** An agent that raises it and follows up.
- **Kill test:** Kill it between follow-ups.
- **Must hold:** One follow-up per week, not one per restart.

### P048 · Income tax refund tracker

*Beginner · wait*

Refunds take weeks.

- **Build:** An agent that checks weekly and tells you when it lands.
- **Kill test:** Kill it, restart it.
- **Must hold:** Checks continue weekly. One notification.

### P049 · Scholarship application

*Intermediate · wait · written down*

A student uploads documents; the college verifies; then the government approves.

- **Build:** An agent that runs the application end to end.
- **Kill test:** Kill it while the college verifies.
- **Must hold:** No re-upload asked. The history shows each approval.

### P050 · Land record mutation

*Advanced · wait · written down · resume*

Several offices sign off over months.

- **Build:** An agent that tracks each office and chases them.
- **Kill test:** Kill it at any step a judge picks.
- **Must hold:** It resumes at that step. Every sign-off recorded.


## 6. Developer & ops

### P051 · Deploy with rollback

*Intermediate · once · resume*

Build, migrate the database, deploy, smoke test; roll back on failure.

- **Build:** A deploy agent.
- **Kill test:** Kill it after the migration ran.
- **Must hold:** The migration runs once. The app is either deployed or rolled back.

### P052 · On-call agent

*Intermediate · wait · written down*

An alert fires. Gather logs, page the on-call, escalate if there's no ack in 10 minutes.

- **Build:** An incident agent.
- **Kill test:** Kill it while it waits for the ack.
- **Must hold:** The escalation still fires on time, once.

### P053 · Migrate 10 million rows

*Advanced · resume · once*

A backfill over 10M rows in batches.

- **Build:** A migration agent.
- **Kill test:** Kill it mid-batch, several times.
- **Must hold:** Every row migrated exactly once. It resumes at the right batch.

### P054 · PR review bot

*Beginner · once*

A bot that reviews pull requests with an LLM.

- **Build:** A review agent (a local git repo is fine).
- **Kill test:** Kill it halfway through posting comments.
- **Must hold:** No duplicate comments.

### P055 · Coding agent vs laptop shutdown

*Intermediate · resume · once*

A long refactor across 20 files dies when the laptop sleeps.

- **Build:** A coding agent that edits files one by one.
- **Kill test:** Kill it at file 10.
- **Must hold:** It resumes at file 10. No file edited twice. No LLM call repeated.

### P056 · Certificate renewals

*Beginner · once · resume*

50 domains, renew each TLS cert 30 days before expiry.

- **Build:** A renewal agent (mock the CA).
- **Kill test:** Kill it around domain 25.
- **Must hold:** Each cert renewed once.

### P057 · Give me my data (DPDP)

*Intermediate · wait · once · written down*

A user asks for their data. Collect from 5 services, send a link, delete the export after 7 days.

- **Build:** An export agent.
- **Kill test:** Kill it while it waits out the 7 days.
- **Must hold:** The export is deleted on day 7, once. Every step logged.

### P058 · Delete my account

*Intermediate · wait · once · written down*

A 30-day grace period, cancelled if the user logs in, then delete everywhere.

- **Build:** A deletion agent.
- **Kill test:** Kill it during the grace period.
- **Must hold:** Deleted once after 30 days, or not at all if they logged in.

### P059 · Nightly pipeline

*Beginner · resume*

A 6-step data pipeline that restarts from step 1 when it fails.

- **Build:** A pipeline that resumes.
- **Kill test:** Kill it at step 4.
- **Must hold:** It resumes at step 4.

### P060 · Cloud cost cleanup

*Intermediate · wait · once · written down*

Find idle VMs, ask the owner, wait 3 days, shut down.

- **Build:** A cleanup agent (mock the cloud).
- **Kill test:** Kill it during the 3-day wait.
- **Must hold:** Each VM shut down once, only after the wait.


## 7. HR & workplace

### P061 · Interview scheduler

*Beginner · wait · once*

Three interviewers and a candidate, all busy.

- **Build:** An agent that finds a slot and sends one invite.
- **Kill test:** Kill it while it waits for replies.
- **Must hold:** One invite per person.

### P062 · Employee onboarding

*Intermediate · resume · once · wait*

Laptop, email account, payroll and a welcome kit, spread over a week.

- **Build:** An onboarding agent.
- **Kill test:** Kill it mid-week.
- **Must hold:** One laptop ordered, one account, one kit.

### P063 · Offer letter

*Intermediate · wait · written down · once*

HR, finance and the CEO approve; the candidate has 7 days to accept.

- **Build:** An offer agent.
- **Kill test:** Kill it between approvals and during the 7 days.
- **Must hold:** One offer sent. The deadline still holds.

### P064 · Leave approval

*Beginner · wait · written down*

A leave request waits for the manager.

- **Build:** A leave agent.
- **Kill test:** Kill it while it waits.
- **Must hold:** Still waiting. The decision is recorded.

### P065 · Full and final settlement

*Intermediate · once · wait · written down*

Collect the laptop, compute dues, pay.

- **Build:** An exit agent.
- **Kill test:** Kill it after the payment.
- **Must hold:** Paid once.

### P066 · Shift roster

*Beginner · wait · written down*

A factory publishes a roster; people request swaps; the supervisor approves.

- **Build:** A roster agent.
- **Kill test:** Kill it with swaps pending.
- **Must hold:** Pending swaps survive. Every change logged.

### P067 · Background verification

*Intermediate · wait · written down*

Ask three previous employers; they take up to 2 weeks.

- **Build:** A verification agent that chases them.
- **Kill test:** Kill it during the wait.
- **Must hold:** No employer asked twice.

### P068 · Screen 2,000 resumes

*Beginner · resume*

An LLM scores each resume. That costs money.

- **Build:** A screening agent.
- **Kill test:** Kill it at resume 1,000.
- **Must hold:** It resumes at 1,001. No resume scored twice.

### P069 · Arrears after a raise

*Advanced · once · wait · written down*

200 people got a backdated raise. Compute, approve, pay.

- **Build:** An arrears agent.
- **Kill test:** Kill it mid-payment.
- **Must hold:** Each person paid once. Approval recorded.

### P070 · Campus hiring

*Intermediate · resume · wait · once*

500 students: test, results, interviews.

- **Build:** A hiring-drive agent.
- **Kill test:** Kill it during results.
- **Must hold:** Each student gets one result.


## 8. Education

### P071 · Assignment grading

*Beginner · resume*

300 submissions, graded by an LLM.

- **Build:** A grading agent.
- **Kill test:** Kill it at 150.
- **Must hold:** Nothing graded twice.

### P072 · Fee reminders and late fee

*Beginner · wait · once*

Three reminders, then a late fee.

- **Build:** A fee agent.
- **Kill test:** Kill it between reminders.
- **Must hold:** The late fee is added once.

### P073 · Admissions

*Intermediate · wait · once · written down*

Apply, check documents, test, offer, pay the fee by a deadline.

- **Build:** An admissions agent.
- **Kill test:** Kill it while it waits for the fee.
- **Must hold:** The seat is released if the deadline passes, once.

### P074 · Publish exam results

*Intermediate · once · resume*

5,000 students, one SMS each.

- **Build:** A results agent.
- **Kill test:** Kill it at 2,500.
- **Must hold:** Each student gets one SMS.

### P075 · Workshop certificates

*Beginner · once · resume*

Certificates for everyone who attended (try it on today's attendees).

- **Build:** A certificate agent.
- **Kill test:** Kill it halfway.
- **Must hold:** One email per person.

### P076 · Library overdue

*Beginner · wait*

A book is due; remind, then fine.

- **Build:** A library agent.
- **Kill test:** Kill it, restart it.
- **Must hold:** Reminders on schedule.

### P077 · Parent-teacher meetings

*Beginner · wait · once*

40 parents, 1 teacher, 15-minute slots.

- **Build:** A scheduling agent.
- **Kill test:** Kill it mid-booking.
- **Must hold:** No slot double-booked.

### P078 · Course coach

*Intermediate · wait · resume*

Nudge learners over weeks based on their progress.

- **Build:** A coaching agent.
- **Kill test:** Kill it mid-course.
- **Must hold:** No nudge repeated or skipped.

### P079 · Scholarship payout

*Intermediate · once · written down · wait*

Approved students get paid; a committee approves the list.

- **Build:** A payout agent.
- **Kill test:** Kill it after approval, mid-payout.
- **Must hold:** Each student paid once.

### P080 · Hostel rooms

*Intermediate · wait · once*

Students list preferences; rooms are allocated; pay in 48 hours or lose it.

- **Build:** An allocation agent.
- **Kill test:** Kill it during the 48 hours.
- **Must hold:** Each room given once.


## 9. Logistics & field work

### P081 · Failed delivery retries

*Beginner · wait · once*

Retry the next day, up to 3 times, then return to sender.

- **Build:** A delivery agent.
- **Kill test:** Kill it between attempts.
- **Must hold:** One attempt per day.

### P082 · Truck trip tracker

*Intermediate · wait · written down*

A 3-day trip, checkpoints, delay alerts, proof of delivery.

- **Build:** A trip agent.
- **Kill test:** Kill it mid-trip.
- **Must hold:** No alert repeated. Full trip history.

### P083 · Warehouse pick and pack

*Intermediate · resume · once*

Pick items for an order, pack, label.

- **Build:** A picking agent.
- **Kill test:** Kill it mid-order.
- **Must hold:** No item picked twice.

### P084 · Purchase order approvals

*Intermediate · wait · written down*

Department head, then finance.

- **Build:** A PO agent.
- **Kill test:** Kill it between approvals.
- **Must hold:** Each approval asked once.

### P085 · Cold chain alert

*Intermediate · wait · written down*

A vaccine fridge gets too warm. Alert, wait for an ack, escalate.

- **Build:** An alerting agent.
- **Kill test:** Kill it while it waits for the ack.
- **Must hold:** The escalation still happens.

### P086 · Pay the vendor on delivery

*Intermediate · wait · once*

Pay only after the warehouse confirms receipt.

- **Build:** A vendor-payment agent.
- **Kill test:** Kill it after confirmation, before payment.
- **Must hold:** Paid once.

### P087 · Field technician

*Beginner · wait · resume*

Assign a job, wait for the completion photo, close it.

- **Build:** A dispatch agent.
- **Kill test:** Kill it while the job is open.
- **Must hold:** Still open after restart.

### P088 · Crop advisory

*Intermediate · wait · resume*

Weekly advice for a season, plus alerts when the weather turns.

- **Build:** An advisory agent.
- **Kill test:** Kill it mid-season.
- **Must hold:** Each week's advice sent once.

### P089 · Mandi price alert

*Beginner · wait*

A farmer wants to sell when onion hits a target price.

- **Build:** A price-watch agent.
- **Kill test:** Kill it, restart it.
- **Must hold:** One alert when the price is hit.

### P090 · Water tanker for a society

*Beginner · wait · once*

Book a tanker when the tank level drops.

- **Build:** A tanker agent.
- **Kill test:** Kill it after booking.
- **Must hold:** One tanker per drop.


## 10. Home & community

### P091 · Apartment maintenance

*Beginner · once · wait*

200 flats, monthly dues, reminders, a late fee.

- **Build:** A maintenance agent.
- **Kill test:** Kill it mid-month.
- **Must hold:** One late fee per flat.

### P092 · Visitor approval

*Beginner · wait*

The guard asks the resident; no reply in 5 minutes means no entry.

- **Build:** A gate agent.
- **Kill test:** Kill it while it waits.
- **Must hold:** The timeout still fires.

### P093 · Meetup organiser

*Intermediate · wait · once · resume*

RSVPs, a waitlist, reminders, certificates after (think AI Yatra).

- **Build:** An event agent.
- **Kill test:** Kill it during RSVPs.
- **Must hold:** No double seats. One reminder each.

### P094 · Wedding vendors

*Advanced · wait · once · written down*

Caterer, decorator, venue. Payments in milestones. The family approves each.

- **Build:** A wedding agent.
- **Kill test:** Kill it between milestones.
- **Must hold:** Each milestone paid once.

### P095 · SIP rebalancer

*Intermediate · wait · once*

Rebalance monthly, but only after you say yes.

- **Build:** A finance agent.
- **Kill test:** Kill it while it waits for you.
- **Must hold:** Rebalanced once per month.

### P096 · Bill pay

*Beginner · once · wait*

Electricity, mobile and gas every month.

- **Build:** A bill agent.
- **Kill test:** Kill it mid-month.
- **Must hold:** Each bill paid once.

### P097 · Medicine reminder for a parent

*Beginner · wait*

Remind; if there's no reply in 30 minutes, call family.

- **Build:** A reminder agent.
- **Kill test:** Kill it during the 30 minutes.
- **Must hold:** The family is still called on time.

### P098 · Volunteer roster

*Beginner · wait · once*

A temple or NGO event needs 50 volunteers across shifts.

- **Build:** A roster agent.
- **Kill test:** Kill it mid-signup.
- **Must hold:** No shift double-booked.

### P099 · Medical crowdfunding

*Intermediate · once · wait · written down*

Collect donations; pay the hospital when the target is reached.

- **Build:** A fundraising agent.
- **Kill test:** Kill it when the target is hit.
- **Must hold:** The hospital is paid once. Every donation is recorded.

### P100 · Your own agent

*Open · resume · once · wait · written down*

Bring any agent you already use or built.

- **Build:** Make it survive a kill -9.
- **Kill test:** Kill it wherever the judges point.
- **Must hold:** It finishes, with nothing done twice.
