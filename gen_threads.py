"""Generates synthetic community threads into simulated_responses.json (community.threads).
Keeps the hand-written threads (ids t1..t14) and appends synthetic ones. Re-run to regenerate."""
import json, random, pathlib
random.seed(26)
P = pathlib.Path(__file__).parent / "simulated_responses.json"
d = json.loads(P.read_text())
schools = {s["id"]: s for s in d["schools"]}
hand = [t for t in d["community"]["threads"] if not t.get("synthetic")]
for t in hand:
    t.setdefault("tags", [])
tagmap = {"t3":["test","nonprofit"],"t5":["international","finance"],"t6":["international","tech"],"t7":["tech"],"t8":["nonprofit"],"t9":["finance"],"t11":["nonprofit","consulting"],"t12":["international","test"],"t13":[],"t1":["consulting","tech"],"t10":[]}
for t in hand: t["tags"] = sorted(set(t["tags"]) | set(tagmap.get(t["id"], [])))

first = ["chicago","boston","bay_area","nyc","delhi","lagos","seoul","sao_paulo","london","toronto","mumbai","shanghai","austin","dc","manila","nairobi","berlin","mexico_city","jakarta","dubai"]
second = ["dreamer","bound","hopeful","applicant","mba","to_b_school","next","2027","grind","optimist","planner","quant","pm","analyst","consultant","banker","engineer","founder"]
def handle(): return random.choice(first) + "_" + random.choice(second) + (str(random.randint(1,99)) if random.random() < .35 else "")
inds = [("Consulting","consulting"),("Tech","tech"),("Finance","finance"),("Nonprofit","nonprofit"),("Healthcare","other"),("Military","other"),("Energy","other"),("Engineering","tech"),("Marketing","other"),("Big Four","consulting")]
countries = ["India","US","China","Nigeria","Brazil","UK","Canada","Mexico","Korea","Germany","Kenya","Indonesia","Philippines","UAE"]
def flair():
    r = random.random(); ind = random.choice(inds)[0]; g = random.choice([645,655,665,675,685,695,705,715,725,735])
    if r < .45: return f"R{random.choice([1,1,2])} applicant, {g}, {ind}"
    if r < .65: return f"{random.choice(countries)}, R{random.choice([1,2])}, {g}"
    if r < .8: return random.choice(["Admitted last cycle","Current student","Alum","Prepping"])
    return f"Prepping, {ind}"

T = {
 "invites": [
  ("{S} {R} interview invites: post your stats", "Invite landed in my inbox about an hour ago. Let's keep a running list of profiles so everyone can see how the waves are going.", ["tracker"]),
  ("Still nothing from {S} {R}. Is silence bad?", "Submitted on the deadline day and nothing yet. Some people on here already have invites. Should I be worried?", []),
  ("{S} {R} invite after {N} weeks of silence", "Just want to give hope to anyone still waiting. I had given up and the invite came this morning.", []),
  ("{S}: invite came without the email, check your portal", "My status page changed before any email arrived. Worth checking if you're anxious.", []),
  ("International applicants: any {S} {R} invites yet?", "Applied from abroad and wondering if international invites come in a separate wave for {S}.", ["international"]),
  ("{S} {R} waves: is there a pattern this year?", "Trying to piece together whether invites go out by region or by submission date. Share when you got yours.", []),
  ("Invited to {S} with a below-median GMAT", "I'm {N}0 points under the median and still got the invite. Essays and recommendations clearly matter.", ["test"]),
  ("Rejected without interview at {S}. What now?", "Disappointing morning. Planning to reapply or move to R2 elsewhere. How did others handle the ding?", []),
 ],
 "decisions": [
  ("{S} vs {S2}: help me decide", "Fortunate to have both offers. {S} has the brand I wanted, {S2} has better scholarship money. What would you weigh most?", ["money"]),
  ("Admitted to {S} {R}!", "Still in shock. {N} years of work experience and two GMAT attempts. Happy to answer questions for anyone in future rounds.", []),
  ("Waitlisted at {S}. Worth sending an update letter?", "I got promoted since I applied. Does a waitlist update actually move the needle at {S}?", []),
  ("Should I accept {S} or wait for {S2} R2?", "Deposit deadline for {S} is before I hear from {S2}. Is it worth losing the deposit?", ["money"]),
  ("Deferred enrollment at {S}: anyone done it?", "Family situation means I may need a year. Curious how flexible {S} is with deferrals.", []),
  ("Visa timelines after an admit to {S}", "Got in and now worrying about the visa process. How early did international students start?", ["international"]),
 ],
 "test": [
  ("{G} on GMAT Focus: my study plan", "Took me {N} weeks. Biggest gains came from timed Data Insights sets and a strict error log. Ask me anything.", []),
  ("Retake or apply with a {G}?", "My target schools have medians around {G2}. I'm torn between retaking and putting the time into essays instead.", []),
  ("Best free resources for GMAT Focus verbal", "I'm strong in quant but critical reasoning keeps dragging me down. What helped you most?", []),
  ("GRE {Q} vs GMAT: which looks better to {S}?", "I scored better on the GRE. Will {S} view it the same way as a GMAT?", ["international"]),
  ("Test day disaster: second attempt advice", "Panicked on the first section and never recovered. Tips for staying calm on the retake?", []),
  ("Working full time and studying: realistic weekly hours?", "I'm doing about ten hours a week with a demanding job. Is that enough for a 100 point improvement?", []),
 ],
 "essays": [
  ("Feedback swap for {S} essays", "Looking for two or three people to swap drafts with this week. I'll give honest notes in return.", []),
  ("How long did your {S} essay take?", "I'm on draft seven and it still doesn't feel right. Curious how many drafts others needed.", []),
  ("Writing about a career switch for {S}", "Moving from {I} to product management. How did you make the why convincing?", []),
  ("Is it okay to mention failure in the {S} essay?", "My best leadership story is about a project that failed. Is that risky?", []),
  ("Choosing recommenders when your boss doesn't know", "I haven't told my manager I'm applying. Who did you pick instead?", []),
  ("Optional essay: explaining a low undergrad GPA", "My GPA was hurt by one bad year. How much detail should I give in the optional essay?", ["international"]),
 ],
 "career": [
  ("{I} to consulting via {S}: realistic?", "Five years in {I} and I want to recruit for consulting. Did {S} help people with my background make the switch?", ["consulting"]),
  ("Post-MBA tech PM recruiting in this market", "Hearing mixed things about tech hiring. Second years, how did recruiting go for you this year?", ["tech"]),
  ("Staying in finance after {S}: is the MBA worth it?", "I'm already in investment banking. Is the MBA a must for moving up, or a nice-to-have?", ["finance"]),
  ("Working in the US after the MBA as an international", "What are realistic options for staying after graduation? How did your school's career office help?", ["international"]),
  ("Entrepreneurship at {S}: how real is the support?", "I want to start a company during the program. Has anyone used {S}'s resources for that?", []),
  ("Coming from {I}: did you feel behind in the core?", "No business background here. How tough was the first term for non-traditional students?", ["nonprofit"]),
 ],
 "money": [
  ("Scholarship from {S}: how much did you get?", "Got a partial award and wondering how it compares. Share your amounts if you're comfortable.", []),
  ("Loans for international students without a US cosigner", "Which lenders worked for you? Options seem limited without a cosigner.", ["international"]),
  ("Is {S} worth full price?", "No scholarship offer. Trying to decide if the brand justifies the total cost.", []),
  ("Budgeting for living costs near {S}", "Rent near campus looks expensive. What do current students actually spend each month?", []),
  ("Fellowships for nonprofit applicants", "Are there fellowships specifically for people coming from the public or nonprofit sector?", ["nonprofit"]),
 ],
}
C = {
 "invites": ["Congrats! Mind sharing your work experience?","Still waiting here. Refreshing the portal way too often.","Got mine yesterday. Interview slots fill fast, book early.","Same boat. Trying to stay off this thread for my sanity.","Invited with a similar profile. Good luck to everyone waiting!","No news for me yet. Last year they ran over several days.","Did you get an email or did the portal update first?"],
 "decisions": ["Visit both if you can. Culture fit matters more than rankings.","Ask both schools to connect you with current students in your target industry.","I'd take the money unless the brand gap is huge for your goal.","Congratulations! That's a huge achievement.","I sent an update letter and it helped. Keep it short and specific.","Think about where you want to live after graduation."],
 "test": ["Error logs changed everything for me too.","Retake if the gap to the median is more than 20 points.","Timed practice is the most underrated part of prep.","Ten hours a week worked for me, but it took four months.","I switched to the GRE and scored much better.","The official practice tests are the most realistic."],
 "essays": ["Happy to swap. Sending you a message.","Failure stories work if you show what you changed afterwards.","Draft seven is normal. Mine took nine.","Specific beats impressive. Admissions readers can tell.","Pick a recommender who has seen you lead, even if they're not your boss.","Keep the optional essay short and factual."],
 "career": ["I made that switch. Network early and practice cases from day one.","Tech recruiting picked up later in the year for us.","Your background is an asset if you frame it as problem solving.","The career office was helpful but the alumni network did more.","The first term is tough but study groups make a big difference.","Start conversations with second years before you even arrive."],
 "money": ["It's always worth asking for a reconsideration politely.","Some schools have their own loan programs for internationals.","Living with roommates cut my costs a lot.","Check the school's financial aid page for named fellowships.","Full price can still be worth it if it gets you to your goal."],
}
inds_txt = ["engineering","the military","nonprofit work","healthcare","teaching","energy","government","marketing"]
ids = [k for k in schools]
top = ["hbs","gsb","wharton","booth","kellogg","sloan","cbs","haas","tuck","yale","ross","fuqua","insead","lbs","isb","stern","darden","anderson"]
out = []; n = 0; seen = set(t["title"] for t in hand)
for topic, temps in T.items():
    for _ in range({"invites":24,"decisions":16,"test":16,"essays":16,"career":16,"money":12}[topic]):
        for _try in range(30):
            title, body, tags = random.choice(temps)
            s1 = random.choice(top if random.random() < .7 else ids); s2 = random.choice([x for x in top if x != s1])
            if title.replace("{S}", schools[s1]["short"]).replace("{S2}", schools[s2]["short"]) not in seen or "{G}" in title: break
        g = random.choice([645,665,675,685,695,705,715,725]); g2 = g + random.choice([10,20,30])
        v = {"S": schools[s1]["short"], "S2": schools[s2]["short"], "R": random.choice(["R1","R1","R2"]), "N": random.randint(2,9), "G": g, "G2": g2, "Q": random.randint(318,332), "I": random.choice(inds_txt)}
        fm = lambda x: x.format(**v)
        school_specific = "{S}" in title or "{S}" in body
        r = random.random()
        if r < .32: mins = random.randint(1, 110); votes = random.randint(1, 35)
        elif r < .72: mins = random.randint(120, 4300); votes = random.randint(15, 420)
        else: mins = random.randint(4320, 43000); votes = random.randint(120, 2600 if topic in ("test","career","money","essays") else 700)
        fl = flair(); tg = set(tags)
        for word, tag in [("Consulting","consulting"),("Tech","tech"),("Finance","finance"),("Nonprofit","nonprofit"),("Big Four","consulting"),("Engineering","tech")]:
            if word in fl: tg.add(tag)
        if any(c in fl for c in countries if c != "US"): tg.add("international")
        if topic == "test": tg.add("test")
        k = random.randint(0, 2) if votes < 30 else random.randint(2, 4) if votes < 300 else random.randint(4, 6)
        cm = []
        for c in random.sample(C[topic], min(k, len(C[topic]))):
            cm.append({"author": handle(), "flair": flair(), "mins": max(0, mins - random.randint(1, max(2, mins - 1))), "votes": random.randint(0, max(3, votes // 4)), "text": c})
        n += 1
        t = {"id": f"s{n}", "synthetic": True, "school": s1 if school_specific else None, "topic": topic, "title": fm(title), "author": handle(), "flair": fl, "mins": mins, "votes": votes, "body": fm(body), "tags": sorted(tg), "comments": cm}
        if "tracker" in tags and mins < 3000:
            inv = random.randint(20, 240); t["tracker"] = {"invites": inv, "noinvite": random.randint(0, inv // 3), "waiting": random.randint(200, 1500)}
        t["tags"] = [x for x in t["tags"] if x != "tracker"]
        if t["title"] in seen: continue
        seen.add(t["title"]); out.append(t)
d["community"]["threads"] = hand + out
P.write_text(json.dumps(d, indent=2, ensure_ascii=False))
print(len(hand), "hand-written +", len(out), "synthetic")
