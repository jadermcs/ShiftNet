"""Generate seed/seed.sql (SQLite) from the sample lexicon used in the design prototype.

Dates are illustrative. Run from backend/: python3 seed/generate_seed.py > seed/seed.sql
Load it into an empty database with `shiftnet seed`.
"""

import json
import uuid

OED = ("Oxford English Dictionary", "dictionary")

# id, lemma, pos, year, date label, gloss, options
SENSES = [
    ("cloud.n.01", "cloud", "noun", 900, "Old English", "a mass of rock; a hill",
     dict(obs=(1400, "by 15th c."), src=("Oxford English Dictionary, cloud n., sense 1", "dictionary"), rel={"hypernym": ["hill"]})),
    ("cloud.n.02", "cloud", "noun", 1300, "c. 1300", "a visible mass of water or ice particles floating in the atmosphere",
     dict(parents=["cloud.n.01"], shift="metaphor", ex=["the clouds parted and the sun came out"],
          src=("Middle English Dictionary, cloud n.", "dictionary"),
          rel={"hypernym": ["atmospheric phenomenon"],
               "hyponym": ["cirrus", "cumulus", "stratus", "nimbus", "cumulonimbus", "altocumulus", "altostratus",
                           "cirrocumulus", "cirrostratus", "stratocumulus", "nimbostratus", "thundercloud", "rain cloud"],
               "derived": ["cloudy", "cloudless"]})),
    ("cloud.n.03", "cloud", "noun", 1400, "c. 1400", "a large number of things moving together through the air",
     dict(parents=["cloud.n.02"], shift="broadening", syn=["cloud", "swarm"], ex=["a cloud of locusts"],
          src=("Middle English Dictionary, cloud n.", "dictionary"), rel={"hypernym": ["multitude", "crowd"]})),
    ("cloud.n.04", "cloud", "noun", 1500, "16th c.", "a state of gloom, trouble or suspicion",
     dict(parents=["cloud.n.02"], shift="metaphor", ex=["he left the company under a cloud"], rel={"hypernym": ["suspicion", "gloom"]})),
    ("cloud.v.01", "cloud", "verb", 1580, "late 16th c.", "to cover or become covered with clouds",
     dict(parents=["cloud.n.02"], shift="other", syn=["cloud", "overcast", "cloud over"], ex=["the sky clouded over by noon"],
          rel={"antonym": ["clear"], "derived": ["clouded"]})),
    ("cloud.v.02", "cloud", "verb", 1600, "c. 1600", "to make unclear, or less able to think clearly",
     dict(parents=["cloud.v.01"], shift="metaphor", syn=["cloud", "becloud", "obscure", "befog"], ex=["anger clouded his judgement"],
          rel={"hypernym": ["confuse"], "antonym": ["clarify"]})),
    ("cloud.n.05", "cloud", "noun", 1970, "1970s", "a cloud-shaped symbol standing for an unspecified network in a diagram",
     dict(parents=["cloud.n.02"], shift="metonymy", src=("Telecommunications engineering diagrams", "citation"), rel={"hypernym": ["symbol"]})),
    ("cloud.n.06", "cloud", "noun", 1990, "1990s", "remote servers reached over the internet, used to store and process data",
     dict(parents=["cloud.n.05", "cloud.n.02"], shift="metaphor", syn=["cloud", "cloud computing"], ex=["back up your photos to the cloud"],
          src=("Computing trade press", "corpus"), rel={"hypernym": ["computing infrastructure"], "derived": ["cloud-based"]})),
    ("mouse.n.01", "mouse", "noun", 800, "Old English", "a small rodent with a pointed snout, small ears and a long tail",
     dict(ex=["a mouse ran under the stove"], rel={"hypernym": ["rodent"], "hyponym": ["house mouse", "field mouse", "harvest mouse", "dormouse"], "derived": ["mousy"]})),
    ("mouse.n.02", "mouse", "noun", 1520, "16th c.", "a quiet or timid person",
     dict(parents=["mouse.n.01"], shift="metaphor", ex=["she was too much of a mouse to complain"], rel={"hypernym": ["person"]})),
    ("mouse.n.03", "mouse", "noun", 1842, "1840s", "a swelling or black eye caused by a blow",
     dict(parents=["mouse.n.01"], shift="metaphor", obs=(1950, "mid-20th c."), src=("Old Bailey Proceedings", "corpus"), syn=["mouse", "black eye", "shiner"])),
    ("mouse.n.04", "mouse", "noun", 1965, "1965", "a hand-operated device that moves a pointer on a computer screen",
     dict(parents=["mouse.n.01"], shift="metaphor", syn=["mouse", "computer mouse"], ex=["click the left mouse button"],
          src=("Research report on display control, 1965", "citation"),
          rel={"hypernym": ["pointing device"], "meronym": ["mouse button", "scroll wheel"], "holonym": ["computer"]})),
    ("mouse.v.01", "mouse", "verb", 1984, "1980s", "to move a pointer or select items using a mouse",
     dict(parents=["mouse.n.04"], shift="other", ex=["mouse over the icon to see its name"], src=("Computing magazines", "corpus"))),
    ("web.n.01", "web", "noun", 850, "Old English", "a piece of cloth woven on a loom", dict(rel={"hypernym": ["fabric"]})),
    ("web.n.02", "web", "noun", 1200, "13th c.", "a net of fine threads spun by a spider",
     dict(parents=["web.n.01"], shift="metaphor", syn=["web", "spiderweb", "cobweb"], ex=["a spider was mending its web"], rel={"hypernym": ["net"]})),
    ("web.n.03", "web", "noun", 1580, "late 16th c.", "an intricate network suggesting something woven",
     dict(parents=["web.n.02"], shift="metaphor", ex=["a web of lies"], rel={"hypernym": ["network"]})),
    ("web.n.04", "web", "noun", 1990, "1990", "the system of linked documents on the internet",
     dict(parents=["web.n.03"], shift="metaphor", syn=["web", "World Wide Web", "WWW"], ex=["she found the recipe on the web"],
          src=("Project proposal, 1990", "citation"), rel={"hypernym": ["computer network"], "meronym": ["web page", "website"], "derived": ["webby"]})),
    ("troll.v.01", "troll", "verb", 1606, "17th c.", "to fish by trailing a baited line behind a moving boat",
     dict(syn=["troll", "trawl"], rel={"hypernym": ["fish"]})),
    ("troll.n.01", "troll", "noun", 1840, "1840s", "a giant or dwarf of Scandinavian folklore living in caves or hills",
     dict(rel={"hypernym": ["mythical being"]})),
    ("troll.v.02", "troll", "verb", 1992, "1992", "to post deliberately provocative messages online",
     dict(parents=["troll.v.01"], shift="metaphor", ex=["he was trolling the forum again"], src=("Usenet archive", "corpus"), rel={"hypernym": ["provoke"]})),
    ("troll.n.02", "troll", "noun", 1993, "1990s", "a person who posts provocative messages online to upset others",
     dict(parents=["troll.v.02", "troll.n.01"], shift="metonymy", syn=["troll", "internet troll"], ex=["don’t feed the trolls"],
          src=("Usenet archive", "corpus"), rel={"hypernym": ["person"], "derived": ["trolling"]})),
    ("virus.n.01", "virus", "noun", 1390, "late 14th c.", "venom, as of a snake; a poisonous substance",
     dict(obs=(1800, "by 19th c."), src=("Middle English Dictionary, virus n.", "dictionary"))),
    ("virus.n.02", "virus", "noun", 1892, "1890s", "an infective agent that multiplies only inside the living cells of an organism",
     dict(parents=["virus.n.01"], shift="narrowing", src=("Medical journals", "corpus"),
          rel={"hypernym": ["microorganism", "infectious agent"], "derived": ["viral"]})),
    ("virus.n.03", "virus", "noun", 1972, "1970s", "a program that copies itself into other programs and spreads between computers",
     dict(parents=["virus.n.02"], shift="metaphor", syn=["virus", "computer virus"], ex=["the virus deleted every file"], rel={"hypernym": ["malware"]})),
    ("viral.adj.01", "viral", "adjective", 1944, "1940s", "of, relating to or caused by a virus",
     dict(parents=["virus.n.02"], shift="other", ex=["a viral infection"], rel={"derived": ["virus"]})),
    ("viral.adj.02", "viral", "adjective", 1989, "1980s", "spreading quickly from person to person, especially online",
     dict(parents=["viral.adj.01"], shift="metaphor", syn=["viral", "go viral"], ex=["the video went viral"], src=("Marketing press", "corpus"))),
    ("nice.adj.01", "nice", "adjective", 1300, "c. 1300", "foolish or ignorant",
     dict(obs=(1600, "by 17th c."), src=("Middle English Dictionary, nice adj.", "dictionary"))),
    ("nice.adj.02", "nice", "adjective", 1520, "16th c.", "requiring great precision or care; subtle",
     dict(parents=["nice.adj.01"], shift="other", ex=["a nice distinction"], syn=["nice", "subtle", "fine"])),
    ("nice.adj.03", "nice", "adjective", 1760, "mid-18th c.", "pleasant or agreeable",
     dict(parents=["nice.adj.02"], shift="amelioration", ex=["we had a nice time"], syn=["nice", "pleasant"],
          rel={"antonym": ["nasty"], "derived": ["nicely", "niceness"]})),
]

# Cited works: key, kind, title, author, publisher, published label, year, url, identifier, accessed on
SOURCES = [
    ("kjv", "book", "The Holy Bible (King James Version)", None, "Robert Barker", "1611", 1611, None, None, None),
    ("hamlet", "book", "Hamlet, Prince of Denmark", "William Shakespeare", None, "c. 1600", 1600, None, None, None),
    ("richard3", "book", "Richard III", "William Shakespeare", None, "1597", 1597, None, None, None),
    ("wordsworth", "book", "Poems, in Two Volumes", "William Wordsworth", "Longman", "1807", 1807, None, None, None),
    ("marmion", "book", "Marmion: A Tale of Flodden Field", "Walter Scott", "Archibald Constable", "1808", 1808, None, None, None),
    ("origin", "book", "On the Origin of Species", "Charles Darwin", "John Murray", "1859", 1859, None, None, None),
    ("northanger", "book", "Northanger Abbey", "Jane Austen", "John Murray", "1817", 1817, None, None, None),
    ("www-proposal", "website", "WorldWideWeb: Proposal for a HyperText Project", "Tim Berners-Lee and Robert Cailliau", "CERN",
     "12 November 1990", 1990, "https://www.w3.org/Proposal.html", None, "2026-10-22"),
    ("cohen", "article", "Computer Viruses: Theory and Experiments", "Fred Cohen", "Proceedings of the 7th DoD/NBS Computer Security Conference",
     "1984", 1984, None, None, None),
    ("schmidt", "other", "Conversation with Eric Schmidt, Search Engine Strategies Conference", "Eric Schmidt", "Search Engine Strategies",
     "9 August 2006", 2006, None, None, None),
]

# sense id, source key, year, date label, locator, quote, validation
ATTESTATIONS = [
    ("cloud.n.02", "kjv", 1611, None, "Genesis 9:13",
     "I doe set my bow in the cloud, and it shall be for a token of a couenant betweene me and the earth.", "editorial"),
    ("cloud.n.02", "kjv", 1611, None, "Exodus 13:21",
     "And the LORD went before them by day in a pillar of a cloud, to lead them the way.", "editorial"),
    ("cloud.n.02", "hamlet", 1600, "c. 1600", "Act 3, scene 2",
     "Do you see yonder cloud that's almost in shape of a camel?", "editorial"),
    ("cloud.n.02", "wordsworth", 1807, None, None,
     "I wandered lonely as a cloud / That floats on high o'er vales and hills", "editorial"),
    ("cloud.n.04", "richard3", 1597, None, "Act 1, scene 1",
     "And all the clouds that lour'd upon our house / In the deep bosom of the ocean buried.", "editorial"),
    ("cloud.n.06", "schmidt", 2006, "9 August 2006", None,
     "It starts with the premise that the data services and architecture should be on servers. "
     "We call it cloud computing; they should be in a \"cloud\" somewhere.", "automatic"),
    ("web.n.03", "marmion", 1808, None, "Canto 6, stanza 17",
     "O, what a tangled web we weave, / When first we practise to deceive!", "editorial"),
    ("web.n.03", "origin", 1859, None, "ch. 3",
     "I am tempted to give one more instance showing how plants and animals, most remote in the scale of nature, "
     "are bound together by a web of complex relations.", "editorial"),
    ("web.n.04", "www-proposal", 1990, "November 1990", None,
     "HyperText is a way to link and access information of various kinds as a web of nodes in which the user can browse at will.",
     "editorial"),
    ("virus.n.03", "cohen", 1984, None, None,
     "We define a computer 'virus' as a program that can 'infect' other programs by modifying them to include "
     "a possibly evolved copy of itself.", "editorial"),
    ("nice.adj.03", "northanger", 1817, None, "ch. 14",
     "This is a very nice day, and we are taking a very nice walk; and you are two very nice young ladies. "
     "Oh! It is a very nice word indeed! It does for everything.", "manual"),
]

# WordNet taxonomy above the sample senses, abridged from Open English WordNet.
# label: (pos, hypernym label or None for a root, gloss). Every "hypernym" relation above must appear here.
TAXONOMY = {
    "entity": ("noun", None, "that which is perceived or known or inferred to have its own distinct existence"),
    "physical entity": ("noun", "entity", "an entity that has physical existence"),
    "abstraction": ("noun", "entity", "a general concept formed by extracting common features from specific examples"),
    "object": ("noun", "physical entity", "a tangible and visible entity"),
    "whole": ("noun", "object", "an assemblage of parts that is regarded as a single entity"),
    "natural object": ("noun", "whole", "an object occurring naturally; not made by man"),
    "geological formation": ("noun", "natural object", "the geological features of the earth"),
    "hill": ("noun", "geological formation", "a local and well-defined elevation of the land"),
    "living thing": ("noun", "whole", "a living (or once living) entity"),
    "organism": ("noun", "living thing", "a living thing that has (or can develop) the ability to act or function independently"),
    "person": ("noun", "organism", "a human being"),
    "animal": ("noun", "organism", "a living organism characterized by voluntary movement"),
    "mammal": ("noun", "animal", "any warm-blooded vertebrate having the skin more or less covered with hair"),
    "rodent": ("noun", "mammal", "relatively small placental mammals having a single pair of constantly growing incisor teeth"),
    "microorganism": ("noun", "organism", "any organism of microscopic size"),
    "artifact": ("noun", "whole", "a man-made object taken as a whole"),
    "fabric": ("noun", "artifact", "artifact made by weaving or felting or knitting or crocheting natural or synthetic fibers"),
    "net": ("noun", "fabric", "an open fabric of string or rope or wire woven together at regular intervals"),
    "instrumentality": ("noun", "artifact", "an artifact that is instrumental in accomplishing some end"),
    "device": ("noun", "instrumentality", "an instrumentality invented for a particular purpose"),
    "input device": ("noun", "device", "a device that puts information into a computer"),
    "pointing device": ("noun", "input device", "a device for moving a pointer on a computer screen"),
    "system": ("noun", "instrumentality", "instrumentality that combines interrelated interacting artifacts designed to work as a coherent entity"),
    "network": ("noun", "system", "an interconnected system of things or people"),
    "computer network": ("noun", "network", "a network of computers"),
    "computing infrastructure": ("noun", "system", "the hardware, software and services that computing runs on"),
    "process": ("noun", "physical entity", "a sustained phenomenon or one marked by gradual changes through a series of states"),
    "phenomenon": ("noun", "process", "any state or process known through the senses rather than by intuition or reasoning"),
    "natural phenomenon": ("noun", "phenomenon", "all phenomena that are not artificial"),
    "physical phenomenon": ("noun", "natural phenomenon", "a natural phenomenon involving the physical properties of matter and energy"),
    "atmospheric phenomenon": ("noun", "physical phenomenon", "a physical phenomenon associated with the atmosphere"),
    "causal agent": ("noun", "physical entity", "any entity that produces an effect or is responsible for events or results"),
    "infectious agent": ("noun", "causal agent", "an agent that can cause infection"),
    "group": ("noun", "abstraction", "any number of entities considered as a unit"),
    "multitude": ("noun", "group", "a large indefinite number"),
    "crowd": ("noun", "group", "a large number of things or people considered together"),
    "attribute": ("noun", "abstraction", "an abstraction belonging to or characteristic of an entity"),
    "state": ("noun", "attribute", "the way something is with respect to its main attributes"),
    "feeling": ("noun", "state", "the experiencing of affective and emotional states"),
    "suspicion": ("noun", "feeling", "the state of being suspected"),
    "gloom": ("noun", "feeling", "a feeling of melancholy apprehension"),
    "psychological feature": ("noun", "abstraction", "a feature of the mental life of a living organism"),
    "cognition": ("noun", "psychological feature", "the psychological result of perception and learning and reasoning"),
    "imaginary being": ("noun", "cognition", "a creature of the imagination; a person that exists only in legends or myths or fiction"),
    "mythical being": ("noun", "imaginary being", "an imaginary being of myth or fable"),
    "communication": ("noun", "abstraction", "something that is communicated by or to or between people or groups"),
    "signal": ("noun", "communication", "any nonverbal action or gesture that encodes a message"),
    "symbol": ("noun", "signal", "an arbitrary sign that has acquired a conventional significance"),
    "written communication": ("noun", "communication", "communication by means of written symbols"),
    "software": ("noun", "written communication", "written programs or procedures or rules and associated documentation"),
    "malware": ("noun", "software", "malicious software designed to damage a computer or gain unauthorized access to it"),
    "change": ("verb", None, "cause to change; make different"),
    "confuse": ("verb", "change", "make unclear, indistinct, or blurred"),
    "arouse": ("verb", "change", "call forth (emotions, feelings, and responses)"),
    "provoke": ("verb", "arouse", "provide the needed stimulus for"),
    "get": ("verb", None, "come into the possession of something concrete or abstract"),
    "catch": ("verb", "get", "take hold of so as to seize or restrain or stop the motion of"),
    "fish": ("verb", "catch", "catch or try to catch fish or shellfish"),
}

POS_LETTER = {"noun": "n", "verb": "v", "adjective": "a", "adverb": "r"}


def synset_id(label, pos):
    return f"wn-{label.replace(' ', '_')}-{POS_LETTER[pos]}"


# Stable ids, so regenerating the seed keeps attestation and source ids (and any links to them).
NS = uuid.UUID("6f1d4f7e-3b8a-4c38-9a8e-5d0c1e2b7a10")


def lit(v):
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return lit(json.dumps(v, ensure_ascii=False))
    return "'" + str(v).replace("'", "''") + "'"


def main():
    senses, parents, lemmas, relations = [], [], [], []
    for sid, lemma, pos, year, label, gloss, o in SENSES:
        src, src_type = o.get("src", OED)
        obs_year, obs_label = o.get("obs", (None, None))
        senses.append(
            f"  ({lit(sid)}, {lit(lemma)}, {lit(pos)}, {lit(gloss)}, {lit(o.get('ex', []))}, {lit(label)}, {year}, "
            f"{lit(obs_year)}, {lit(obs_label)}, {lit(o.get('shift', 'root'))}, {lit(src)}, {lit(src_type)})"
        )
        for i, p in enumerate(o.get("parents", [])):
            parents.append(f"  ({lit(sid)}, {lit(p)}, {i}, {lit(src)})")
        for i, w in enumerate(o.get("syn", [lemma])):
            lemmas.append(f"  ({lit(sid)}, {lit(w)}, {i})")
        for rtype, targets in o.get("rel", {}).items():
            for i, t in enumerate(targets):
                relations.append(f"  ({lit(sid)}, {lit(rtype)}, {lit(t)}, {i})")

    print("-- Generated by seed/generate_seed.py. Sample lexicon; dates are illustrative.\n")
    print("insert into senses (id, lemma, pos, gloss, examples, date_label, date_earliest, "
          "obsolete_year, obsolete_label, shift, source, source_type) values")
    print(",\n".join(senses) + ";\n")
    print("insert into sense_parents (sense_id, parent_id, position, source) values")
    print(",\n".join(parents) + ";\n")
    print("insert into sense_lemmas (sense_id, lemma, position) values")
    print(",\n".join(lemmas) + ";\n")
    print("insert into relations (sense_id, type, target_lemma, position) values")
    print(",\n".join(relations) + ";\n")

    # Taxonomy: the backbone, one synset per dated sense, and its listed hyponyms as leaf synsets.
    synsets, hypernyms = {}, []
    for label, (pos, parent, gloss) in TAXONOMY.items():
        sid = synset_id(label, pos)
        synsets[sid] = (pos, [label], gloss)
        if parent:
            assert parent in TAXONOMY and TAXONOMY[parent][0] == pos, (label, parent)
            hypernyms.append((sid, synset_id(parent, pos), 0))
    for sid, lemma, pos, year, label, gloss, o in SENSES:
        rel = o.get("rel", {})
        synsets[sid] = (pos, o.get("syn", [lemma]), gloss)
        for i, h in enumerate(rel.get("hypernym", [])):
            assert TAXONOMY.get(h, (None,))[0] == pos, f"{sid}: hypernym {h!r} missing from TAXONOMY"
            hypernyms.append((sid, synset_id(h, pos), i))
        for h in rel.get("hyponym", []):
            hid = synset_id(h, pos)
            synsets.setdefault(hid, (pos, [h], None))
            hypernyms.append((hid, sid, 0))
    print("insert into synsets (id, pos, lemmas, gloss) values")
    print(",\n".join(f"  ({lit(k)}, {lit(pos)}, {lit(lemmas)}, {lit(gloss)})" for k, (pos, lemmas, gloss) in synsets.items()) + ";\n")
    print("insert into synset_hypernyms (synset_id, hypernym_id, position) values")
    print(",\n".join(f"  ({lit(a)}, {lit(b)}, {i})" for a, b, i in hypernyms) + ";\n")
    print("update senses set synset_id = id where id in (select id from synsets);\n")

    sources = [
        f"  ({lit(str(uuid.uuid5(NS, 'source:' + key)))}, {lit(kind)}, {lit(title)}, {lit(author)}, {lit(publisher)}, "
        f"{lit(label)}, {lit(year)}, {lit(url)}, {lit(ident)}, {lit(accessed)})"
        for key, kind, title, author, publisher, label, year, url, ident, accessed in SOURCES
    ]
    known = {key for key, *_ in SOURCES}
    attestations = []
    for i, (sid, key, year, label, locator, quote, validation) in enumerate(ATTESTATIONS):
        assert key in known, key
        attestations.append(
            f"  ({lit(str(uuid.uuid5(NS, f'attestation:{sid}:{i}')))}, {lit(sid)}, {lit(str(uuid.uuid5(NS, 'source:' + key)))}, "
            f"{lit(quote)}, {lit(year)}, {lit(label)}, {lit(locator)}, {lit(validation)}, "
            + ("null" if validation == "editorial" else "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')") + ")"
        )
    print("insert into sources (id, kind, title, author, publisher, published_label, published_year, url, identifier, "
          "accessed_on) values")
    print(",\n".join(sources) + ";\n")
    print("insert into attestations (id, sense_id, source_id, quote, year, date_label, locator, validation, validated_at) values")
    print(",\n".join(attestations) + ";")


if __name__ == "__main__":
    main()
