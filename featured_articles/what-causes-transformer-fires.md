---
title: What Causes Transformer Fires, and Why Conventional Protection Often Arrives Too Late
date: 2026-08-10
summary: Oil-filled transformers fail in predictable ways, but the pressure event that follows an internal arc moves faster than most protective devices are designed to handle. A look at the failure data, the physics of tank rupture, and what NFPA 850 actually says about fast depressurization systems.
---

A large oil-filled power transformer is the most valuable single asset in most substations and generating plants. It is also the most energetic thing on the site. A 117/15.2-kV unit in the 37/50/62.5-MVA class can hold on the order of 10,000 gallons of mineral oil, and larger units hold considerably more. When an internal fault ignites that volume, the result is rarely a contained equipment loss. It is a fire that threatens adjacent assets, personnel, and — increasingly — the operator's insurability.

The uncomfortable part is that transformer fires are not especially rare. Industry figures widely cited in the trade press put the probability of a serious transformer fire at roughly 0.06 to 0.1 percent per service year, or about one fire per 1,000 to 1,500 transformer service years. Spread across a 40-year service life, that works out to somewhere between 2.4 and 4 percent of all units causing a fire at some point. For a utility with a fleet in the hundreds, that is not a tail risk. It is a scheduling problem.

This article covers three things: where transformers actually fail, why the failure becomes a fire, and why the protective devices most substations rely on frequently do not act quickly enough to stop it.

## Where transformers actually fail

Failure statistics vary by population, voltage class, and study methodology, but the broad pattern from CIGRE working group data is consistent enough to plan around.

For **substation transformers**, the dominant contributors to major failures are windings at roughly 38 percent, bushings at roughly 24 percent, and tap changers at roughly 20 percent. For **generator step-up units**, the distribution shifts: windings around 29 percent, with bushings and tap changers each closer to 14.5 percent, and a markedly higher contribution from core and magnetic circuit failures — around 11 percent, compared with under 2 percent in substation units. Lead exit, core, and insulation issues each account for a few percent more.

Two of those categories deserve particular attention from a fire standpoint.

**Bushings** are disproportionately dangerous. They sit under continuous high dielectric and thermal stress, and when they fail they tend to fail violently. Analyses of bushing-related incidents have found that more than half are accompanied by fire and serious consequences. The mechanisms are unglamorous and largely preventable: moisture ingress through aged seals and gaskets, partial discharge developing inside the insulation layers, oil leakage degrading oil-impregnated paper, overheating at loose or contaminated connections, and surface tracking accelerated by salt fog or industrial pollution. In some manufacturing-decade cohorts, bushings dominate the failure statistics outright.

**On-load tap changers** are the other recurring offender, and for a structural reason: the OLTC is the only part of the transformer with moving parts operating under load. Dirty or worn contacts, insufficient spring pressure, motor drive faults, and oil starvation in a tap changer compartment that is not properly connected to the main tank all produce the same end state — arcing where arcing was not designed to occur.

**Winding failures**, the largest single category, typically originate in dielectric or mechanical stress. Through-faults impose mechanical forces on the windings; over years, weak bracing, aged supports, and loose clamping allow cumulative deformation. Deformation damages turn-to-turn insulation. Damaged insulation eventually becomes a shorted turn, and a shorted turn becomes an internal arc.

## Why a fault becomes a fire

This is the step that gets glossed over, and it is the one that determines whether a fault is an expensive outage or a catastrophic one.

An internal arc in an oil-filled transformer does not simply burn. It vaporizes the surrounding oil almost instantaneously, generating a large volume of gas in a sealed steel tank. That gas generation produces a **dynamic pressure wave** — a fast-moving pressure peak that propagates through the oil before the tank's overall static pressure has meaningfully risen.

That distinction between dynamic and static pressure is the entire problem.

The tank is a pressure vessel with a finite rupture threshold. If the pressure wave exceeds that threshold, the tank ruptures. Rupture exposes several thousand gallons of hot, aerated oil to atmosphere in the presence of an active electrical arc. From that point, ignition is not really in question, and no suppression system is preventing the fire — it is only fighting one that already exists.

## Why conventional protection is often too slow

Substations are not unprotected. The standard arrangement includes differential and overcurrent relaying, Buchholz relays, sudden pressure relays, and pressure relief valves. Each of these does useful work. The difficulty is that most of them are responding to the wrong thing, or responding to the right thing on the wrong timescale.

**Protective relaying and circuit breakers** clear the fault current, and they are fast by electrical standards. But clearing the source of the arc does not un-generate the gas already produced. The pressure event proceeds on its own schedule.

**Buchholz relays** detect gas accumulation and oil surge. They are well suited to slowly developing incipient faults — the kind that give weeks of warning through dissolved gas analysis. They are not designed as a millisecond-scale response to a low-impedance fault.

**Pressure relief valves** are the device most often assumed to cover this scenario, and the assumption deserves scrutiny. PRVs are engineered to release excess pressure during a *slow* pressure rise. They are calibrated against static pressure. In a fast dynamic event, the pressure wave can reach the tank wall and exceed its rupture threshold before a static-pressure-actuated device has meaningfully opened. The valve is not defective; it is being asked to solve a problem outside its design basis.

The result is a protection gap that is specific and narrow: the interval between the initiation of an internal arc and the mechanical failure of the tank. Everything in the conventional stack is either upstream of that window or downstream of it.

## What NFPA 850 actually says about fast depressurization

This is where the trade literature gets muddy, so it is worth being precise.

**NFPA 850** is the *Recommended Practice for Fire Protection for Electric Generating Plants and High Voltage Direct Current Converter Stations*. Two qualifiers matter. First, it is a Recommended Practice, not a code — it recommends rather than requires, and it is enforceable only where a jurisdiction or an owner's specification adopts it. Second, the material on fast depressurization lives in **Annex A**, which is explanatory material rather than part of the recommendations proper.

What Annex A does is define the concept. In NFPA's committee language, a fast depressurization system is a passive mechanical system designed to depressurize oil-filled equipment — transformers, current-limiting reactors, bushing cable boxes, or load tap changers — a few milliseconds after the occurrence of an internal electrical arc. The operating principle is to use the dynamic pressure peak itself as the trigger, evacuating oil and relieving tank pressure before static pressure has time to develop against the tank wall.

Here is the part that is routinely overstated in vendor materials. NFPA's own technical committee documentation is explicit that the annex treats such a system as a **possible supplement, not an alternative** to passive protection features such as physical barriers and spatial separation. A fast depressurization system does not relieve a designer of the separation distances and firewall provisions that NFPA 850 addresses elsewhere, which remain keyed to oil capacity and adjacency. Any claim that NFPA "requires" or straightforwardly "recommends" these systems is reading more into the document than the document says.

Read accurately, NFPA 850 acknowledges the protection gap described above, defines a class of equipment intended to address it, and declines to treat that equipment as a substitute for the fundamentals.

## The rest of the toolkit

Fast depressurization addresses one specific failure mode. It is not a fire protection strategy on its own, and several other measures do meaningful work:

- **Separation and barriers.** NFPA 850's guidance on spatial separation and fire-rated barrier walls is keyed to insulating liquid volume, with thresholds around 500 and 5,000 gallons driving separation distance and firewall requirements. This remains the foundation.
- **Less-flammable insulating fluids.** Ester-based and other high-fire-point fluids materially change the hazard, and in some configurations can mitigate the need for suppression entirely. Worth evaluating at specification time, when the cost delta is smallest.
- **Dry-type units** eliminate the oil fire risk outright, where the application allows — generally medium- and low-voltage indoor service.
- **Water spray and mist systems**, covered by NFPA 15 and NFPA 750, address exposure protection and suppression once a fire exists.
- **Condition monitoring.** Dissolved gas analysis, bushing power factor testing, and OLTC contact monitoring catch the slow-developing faults well before the fast event. The cheapest transformer fire is the one prevented at the maintenance stage.
- **IEEE 979** (substation fire protection) and **IEEE 980** (oil spill containment and control) cover ground NFPA 850 does not.

## What to take from this

The failure data points somewhere specific. Windings, bushings, and tap changers account for the large majority of major failures, and bushing failures in particular carry an elevated probability of fire. Most of the underlying mechanisms — moisture ingress, contact wear, insulation aging, mechanical loosening — are detectable on a maintenance interval.

But the transition from internal arc to tank rupture happens on a timescale that inspection cannot help with and that most installed protective devices were not designed for. Whether to close that gap with a fast depressurization system is a site-specific engineering and economic judgment, informed by oil volume, adjacency, replacement lead time, and — more often than utilities expect — what an insurance underwriter is willing to write.

Several manufacturers build to the fast depressurization concept described in NFPA 850 Annex A, among them SERGI and Transformer Protector Corp, CTR, and Houston-area manufacturer Sentry Global Solutions. Approaches differ meaningfully in triggering mechanism, whether the depressurization path is genuinely passive, and how the system interacts with the conservator. Those differences are worth interrogating directly with any vendor rather than accepting at datasheet level — a point on which the engineering discussion forums have been notably more skeptical than the marketing literature.

---

*Power Industry News is an independent industry resource. This article is editorial content and is not sponsored. Vendors are named for reference only and their inclusion does not constitute endorsement.*

*Standards references in this article are provided for orientation. Design decisions should be based on the current published editions of NFPA 850, NFPA 15, NFPA 750, IEEE 979, and IEEE 980, and on the requirements of the authority having jurisdiction.*
