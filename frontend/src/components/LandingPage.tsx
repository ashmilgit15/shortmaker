import React from 'react';
import { SignInButton, SignUpButton } from '@clerk/react';
import styles from './LandingPage.module.css';

const FEATURES = [
  {
    icon: 'auto_awesome',
    title: 'AI Highlight Detection',
    desc: 'Gemini 2.0 Flash watches every frame and scores each moment for virality, emotional impact, and retention potential.',
  },
  {
    icon: 'crop_free',
    title: 'Auto 9:16 Reframe',
    desc: 'Smart face-tracking reframes your content perfectly for TikTok, Reels, and YouTube Shorts — zero manual cropping.',
  },
  {
    icon: 'closed_caption',
    title: 'Viral Caption Burn',
    desc: 'Animated, styled captions burned directly into your clips. Maximum engagement, no editor required.',
  },
];

const STEPS = [
  {
    num: '01',
    icon: 'link',
    title: 'Paste Any YouTube URL',
    desc: 'Drop in any YouTube link. We handle downloading, transcription, and analysis automatically.',
  },
  {
    num: '02',
    icon: 'psychology',
    title: 'AI Finds the Best Moments',
    desc: 'Our model ranks each segment by virality score and selects the most engaging clips for short-form.',
  },
  {
    num: '03',
    icon: 'download',
    title: 'Download & Publish',
    desc: 'Vertical, captioned, and perfectly cropped clips are ready in your dashboard — publish in one click.',
  },
];

const STATS = [
  { value: '10x', label: 'Faster Workflow' },
  { value: '99%', label: 'AI Accuracy' },
  { value: '<5 min', label: 'Per Video' },
];

export default function LandingPage() {
  return (
    <div className={styles.page}>
      {/* ── Nav ── */}
      <header className={styles.nav}>
        <div className={styles.navLogo}>
          <div className={styles.navLogoIcon}>
            <span className={`material-symbols-outlined ${styles.navLogoMIcon}`}>movie_edit</span>
          </div>
          <span className={styles.navLogoText}>ShortMaker</span>
        </div>
        <div className={styles.navActions}>
          <div className={styles.navSignIn}>
            <SignInButton mode="modal">
              <button className="btn btn-secondary">Sign In</button>
            </SignInButton>
          </div>
          <SignUpButton mode="modal">
            <button className="btn btn-primary">Get Started Free</button>
          </SignUpButton>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className={styles.hero}>
        <div className={styles.heroBg} aria-hidden="true">
          <div className={styles.orb1} />
          <div className={styles.orb2} />
          <div className={styles.orb3} />
        </div>

        <div className={styles.heroContent}>
          <div className={styles.badge}>
            <span className={`material-symbols-outlined ${styles.badgeIcon}`}>bolt</span>
            AI-POWERED · V3.0
          </div>

          <h1 className={styles.heroH1}>
            Turn YouTube into<br />
            <span className="gradient-text">Viral Clips</span>
          </h1>

          <p className={styles.heroDesc}>
            The ultimate AI workspace for short-form creators. Automatically detect highlights,
            score virality, and export perfect 9:16 clips — in minutes.
          </p>

          <div className={styles.heroCta}>
            <SignUpButton mode="modal">
              <button className={`btn btn-primary ${styles.heroBtn}`}>
                <span className="material-symbols-outlined">bolt</span>
                Start Creating Free
              </button>
            </SignUpButton>
            <SignInButton mode="modal">
              <button className={`btn btn-secondary ${styles.heroBtn}`}>
                Sign In
              </button>
            </SignInButton>
          </div>

          <div className={styles.stats}>
            {STATS.map((s) => (
              <div key={s.label} className={styles.stat}>
                <strong className={styles.statVal}>{s.value}</strong>
                <span className={styles.statLabel}>{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={styles.tag}>Features</span>
          <h2 className={styles.sectionH2}>Everything you need to go viral</h2>
          <p className={styles.sectionDesc}>Built for creators who want speed without sacrificing quality.</p>
        </div>

        <div className={styles.featureGrid}>
          {FEATURES.map((f, i) => (
            <div key={f.title} className={`card ${styles.featureCard}`} style={{ animationDelay: `${i * 0.1}s` }}>
              <div className={styles.featureIconBox}>
                <span className={`material-symbols-outlined ${styles.featureMIcon}`}>{f.icon}</span>
              </div>
              <h3 className={styles.featureTitle}>{f.title}</h3>
              <p className={styles.featureDesc}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section className={styles.stepsSection}>
        <div className={styles.sectionHead}>
          <span className={styles.tag}>Process</span>
          <h2 className={styles.sectionH2}>Go from link to clip in minutes</h2>
        </div>

        <div className={styles.stepsGrid}>
          {STEPS.map((s, i) => (
            <div key={s.num} className={styles.step}>
              <div className={styles.stepTop}>
                <div className={styles.stepIconBox}>
                  <span className={`material-symbols-outlined ${styles.stepMIcon}`}>{s.icon}</span>
                </div>
                {i < STEPS.length - 1 && <div className={styles.stepLine} aria-hidden="true" />}
              </div>
              <span className={styles.stepNum}>{s.num}</span>
              <h3 className={styles.stepTitle}>{s.title}</h3>
              <p className={styles.stepDesc}>{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section className={styles.ctaSection}>
        <div className={styles.ctaCard}>
          <div className={styles.ctaBg} aria-hidden="true" />
          <h2 className={styles.ctaH2}>Ready to go viral?</h2>
          <p className={styles.ctaDesc}>Join creators shipping shorts at 10x speed with AI.</p>
          <SignUpButton mode="modal">
            <button className={`btn btn-primary ${styles.ctaBtn}`}>
              <span className="material-symbols-outlined">rocket_launch</span>
              Start Creating for Free
            </button>
          </SignUpButton>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className={styles.footer}>
        <p>© 2024 ShortMaker · Powered by Gemini AI</p>
      </footer>
    </div>
  );
}
