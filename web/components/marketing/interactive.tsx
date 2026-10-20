"use client";
import { useEffect, useRef, useState, type AnchorHTMLAttributes } from "react";
import { usePathname } from "next/navigation";
import { trackMarketingEvent } from "@/lib/marketing-analytics";
import { tourSteps } from "./demo-data";
import { ActionScene, RecoveryScene, SearchScene, TruthScene } from "./scenes";
type Event = Parameters<typeof trackMarketingEvent>[0];
type Source = Parameters<typeof trackMarketingEvent>[1];

export function MarketingLink({ event, source, children, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { event?: Event; source?: Source }) {
  return <a {...props} onClick={(e) => { if(event) trackMarketingEvent(event, source); if(props.href === "/connect" && event !== "connect_google_ads_click") trackMarketingEvent("connect_google_ads_click", source); onClick?.(e); }}>{children}</a>;
}

export function PageEvents() {
  const pathname = usePathname(); const last = useRef("");
  useEffect(() => {if(last.current === pathname) return;last.current = pathname;if(pathname === "/pricing") trackMarketingEvent("pricing_open", "pricing");if(pathname === "/security") trackMarketingEvent("security_page_open", "security");},[pathname]);
  return null;
}

export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  return <div className="m-mobile-nav" onKeyDown={e=>{if(e.key==="Escape"&&open){setOpen(false);toggle.current?.focus();}}}><button ref={toggle} className="m-menu-toggle" type="button" aria-expanded={open} aria-controls="marketing-mobile-menu" aria-label={open ? "Close navigation" : "Open navigation"} onClick={()=>setOpen(!open)}>{open ? "Close −" : "Menu +"}</button>{open && <nav id="marketing-mobile-menu" aria-label="Mobile navigation"><a href="/product">Product</a><a href="/for-agencies">For agencies</a><a href="/for-brands">For brands</a><a href="/reporting">Reporting</a><a href="/security">Security</a><a href="/pricing">Pricing</a><a href="/login">Sign in ↗</a></nav>}</div>;
}

export function ProductTour({ compact = false }: { compact?: boolean }) {
  const [step,setStep] = useState(0); const [started,setStarted] = useState(false); const completed = useRef(false); const current = tourSteps[step];
  const begin = () => {if(!started){trackMarketingEvent("product_tour_open","product_tour");setStarted(true);}};
  const next = () => {begin();const value=Math.min(step+1,tourSteps.length-1);setStep(value);if(value===tourSteps.length-1&&!completed.current){completed.current=true;trackMarketingEvent("product_tour_complete","product_tour");}};
  return <div id={compact ? undefined : "product-tour"} className={`m-tour${compact ? " m-tour-compact" : ""}`}><h2 className="m-sr-only">Explore the Northstar Roofing case</h2><div className="m-tour-top"><span className="m-eyebrow">NORTHSTAR ROOFING / SYNTHETIC ADVERTISER</span><span>Interactive product walkthrough</span></div><ol className="m-tour-steps" aria-label="Tour progress">{tourSteps.map((s,i)=><li key={s.label} aria-current={step===i?"step":undefined} className={i<=step?"m-step-reached":""}><span>{String(i+1).padStart(2,"0")}</span><span>{s.label}</span></li>)}</ol><div className="m-tour-body"><div className="m-tour-story" aria-live="polite" aria-atomic="true"><span className="m-eyebrow">STEP {step+1} OF {tourSteps.length} / {current.label}</span><h3>{current.title}</h3><p>{current.body}</p><div className="m-tour-controls"><button type="button" className="m-button m-button-secondary" onClick={()=>setStep(Math.max(step-1,0))} disabled={step===0} aria-label="Previous tour step">← Back</button>{step<tourSteps.length-1?<button type="button" className="m-button" onClick={next}>{step===0&&!started?"Start the story":step===5?"Simulate approval":"Continue"} <span aria-hidden="true">→</span></button>:<button type="button" className="m-button" onClick={()=>{setStep(0);setStarted(false);completed.current=false;}}>Replay story ↺</button>}</div><p className="m-note">Demo only. No live account is connected or changed.</p></div><div className="m-tour-scene">{current.view==="search"?<SearchScene/>:current.view==="truth"?<TruthScene/>:current.view==="collision"?<ActionScene blocked/>:current.view==="recovery"?<RecoveryScene/>:<ActionScene applied={current.view==="applied"}/>}</div></div>{!compact && <div className="m-tour-end"><span>Every amount is illustrative. Configuration verification is not financial recovery.</span><MarketingLink href="/connect" event="connect_google_ads_click" source="product_tour">Connect your account ↗</MarketingLink></div>}</div>;
}
