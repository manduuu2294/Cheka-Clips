const getBtn = document.querySelector('[data-action="clip"]')
const body = document.body
const scene = document.getElementById('scene')
const heroRow = document.getElementById('heroRow')
const vpWrap = document.getElementById('vpWrap')
const vpGlow = document.getElementById('vpGlow')
const vpImg = document.getElementById('vpImg')
const vpScanner = document.getElementById('vpScanner')
const vpShimmer = document.getElementById('vpShimmer')
const vpPlay = document.getElementById('vpPlay')
const tlRail = document.getElementById('tlRail')
const railDots = document.querySelectorAll('.tl-rn-dot')
const statusText = document.getElementById('statusText')
const ccClips = document.querySelectorAll('.cc-clip')
const ccFlashes = document.querySelectorAll('.cc-flash')
const title = document.querySelector('.title')
const subtitle = document.querySelector('.subtitle')
const actions = document.querySelector('.actions')
const logo = document.querySelector('.logo')

let activeIdx = 0
let carouselTimer = null
let isProcessing = false

/* ─── INITIAL STATE ─── */
gsap.set([scene,title,subtitle,actions,logo,statusText],{autoAlpha:0})
gsap.set(heroRow,{autoAlpha:0})
gsap.set(vpWrap,{autoAlpha:0,scale:0.9})
gsap.set(vpGlow,{opacity:0})
gsap.set(vpScanner,{left:'-3px',opacity:0})
gsap.set(vpPlay,{scale:0.8,opacity:0})
gsap.set(vpShimmer,{left:'-60%',opacity:0.6})
gsap.set(tlRail,{autoAlpha:0})
gsap.set(railDots,{scale:0})

/* ─── SCANNER LOOP ─── */
const scannerTL = gsap.timeline({paused:true,repeat:-1,repeatDelay:2.5})
scannerTL
  .set(vpScanner,{left:'-3px',opacity:0})
  .to(vpScanner,{opacity:0.5,duration:0.04})
  .to(vpScanner,{left:'100%',duration:0.7,ease:'power2.inOut'})
  .to(vpScanner,{opacity:0,duration:0.2})

/* ─── CAROUSEL — VERTICAL ROULETTE ─── */
function updateRoulette(idx){
  ccClips.forEach((el,i)=>{
    el.classList.remove('is-prev','is-active','is-next')
  })
  railDots.forEach(d=>d.classList.remove('lit'))

  const prev = (idx + 2) % 3
  const next = (idx + 1) % 3

  ccClips[prev].classList.add('is-prev')
  ccClips[idx].classList.add('is-active')
  ccClips[next].classList.add('is-next')

  railDots[idx].classList.add('lit')

  // Flash on active
  ccFlashes[idx].classList.add('impact')
  setTimeout(()=>ccFlashes[idx].classList.remove('impact'),400)
}

function rotateCarousel(){
  if(isProcessing) return
  activeIdx = (activeIdx + 1) % 3
  updateRoulette(activeIdx)
  // Scanner sweep on each rotation
  gsap.set(vpScanner,{left:'-3px',opacity:0})
  gsap.to(vpScanner,{opacity:0.45,duration:0.03,delay:0.08})
  gsap.to(vpScanner,{left:'100%',duration:0.5,ease:'power2.inOut',delay:0.11})
  gsap.to(vpScanner,{opacity:0,duration:0.15,delay:0.61})
}

function startCarousel(){
  stopCarousel()
  carouselTimer = setInterval(rotateCarousel, 3200)
}

function stopCarousel(){
  if(carouselTimer){clearInterval(carouselTimer);carouselTimer=null}
}

/* ─── SHIMMER LOOP — purple sweep ─── */
const shimmerTL = gsap.timeline({paused:true,repeat:-1})
shimmerTL
  .set(vpShimmer,{left:'-60%',opacity:0.7})
  .to(vpShimmer,{left:'160%',duration:3.5,ease:'power1.inOut'})

const clipFloatTL = gsap.timeline({paused:true,repeat:-1,yoyo:true,ease:'sine.inOut'})
clipFloatTL.to('#clipCarousel', {y:-4, duration:3}, 0)

/* ─── ENTRANCE ─── */
const TL = gsap.timeline({delay:0.08,ease:'power3.out'})

TL.to(scene,{autoAlpha:1,duration:0.3})
  .to(logo,{autoAlpha:1,duration:0.25},'<+0.05')
  .to(title,{autoAlpha:1,y:0,duration:0.4},'-=0.1')
  .to(subtitle,{autoAlpha:1,y:0,duration:0.3},'-=0.15')
  .to(actions,{autoAlpha:1,y:0,duration:0.25},'-=0.1')

TL.to(heroRow,{autoAlpha:1,duration:0.01},'<+0.05')
  .to(vpWrap,{autoAlpha:1,scale:1,duration:0.6,ease:'power4.out'},'-=0.1')
  .to(vpGlow,{opacity:1,duration:0.3},'-=0.25')
  .to(vpPlay,{scale:1,opacity:1,duration:0.3,ease:'back.out(1.5)'},'-=0.12')

// Rail appears
TL.to(tlRail,{autoAlpha:1,duration:0.25},'<+0.15')

// Scanner first sweep
TL.set(vpScanner,{left:'-3px',opacity:0},'<+0.1')
  .to(vpScanner,{opacity:0.6,duration:0.03},'>-0.02')
  .to(vpScanner,{left:'100%',duration:0.5,ease:'power2.inOut'},'>-0.02')
  .to(vpScanner,{opacity:0,duration:0.18},'>-0.04')

// Roulette appears
TL.call(()=>{
  updateRoulette(0)
},[],'<+0.15')

// Status appears then fades
TL.to(statusText,{autoAlpha:1,duration:0.2},'>+0.25')
TL.to(statusText,{autoAlpha:0,duration:0.15,delay:0.4},'>+0.2')

// Start all continuous animations
TL.call(()=>{
  scannerTL.play()
  shimmerTL.play()
  clipFloatTL.play()
  startCarousel()
},[],'>+0.15')

/* ─── CLICK SEQUENCE ─── */
const CLICK_TL = gsap.timeline({paused:true})

CLICK_TL.call(()=>{
  isProcessing = true
  stopCarousel()
  scannerTL.pause()
  gsap.set(vpScanner,{left:'-3px',opacity:0})

  ccClips.forEach(el=>el.classList.remove('is-prev','is-active','is-next'))
  ccFlashes.forEach(f => f.classList.remove('impact'))
  railDots.forEach(d => d.classList.remove('lit'))
  gsap.set(statusText,{autoAlpha:0})
},[],0)

// Scanner fast
CLICK_TL.to(vpScanner,{opacity:0.6,duration:0.02},0.03)
  .to(vpScanner,{left:'100%',duration:0.35,ease:'power2.inOut'},'>-0.02')
  .to(vpScanner,{opacity:0,duration:0.08},'>-0.02')

// Status
CLICK_TL.to(statusText,{autoAlpha:1,duration:0.05},0.03)

// All 3 clips appear in sequence
CLICK_TL.call(()=>{
  for(let i=0;i<3;i++){
    setTimeout(()=>{
      const clip=ccClips[i], flash=ccFlashes[i], dot=railDots[i]
      clip.classList.add('is-active')
      dot.classList.add('lit')
      flash.classList.add('impact')
      setTimeout(()=>flash.classList.remove('impact'), 350)
    }, i * 120)
  }
},[],0.06)

/* ─── EXIT ─── */
const EXIT_TL = gsap.timeline({paused:true})
EXIT_TL.to(scene,{opacity:0,scale:0.96,duration:0.3,ease:'power3.in'},0)
  .to([title,subtitle,actions,logo],{opacity:0,y:10,duration:0.18,ease:'power2.in'},0.03)
  .set(body,{backgroundColor:'#000',onComplete:()=>{
    window.location.href='http://localhost:8501?ch=general'
  }},'+=0.1')

/* ─── CLICK HANDLER ─── */
getBtn.addEventListener('click',async e=>{
  e.preventDefault()
  scannerTL.pause()
  shimmerTL.pause()
  clipFloatTL.pause()
  stopCarousel()
  getBtn.classList.add('is-loading')
  body.classList.add('is-processing')
  CLICK_TL.restart()
  await new Promise(r=>setTimeout(r,700))
  body.classList.remove('is-processing')
  EXIT_TL.play()
})
