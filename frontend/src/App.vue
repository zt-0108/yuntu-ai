<script setup lang="ts">
import { defineAsyncComponent, ref } from "vue";

import type { Itinerary } from "./types";
import Home from "./views/Home.vue";

const History = defineAsyncComponent(() => import("./views/History.vue"));
const Result = defineAsyncComponent(() => import("./views/Result.vue"));

const currentView = ref<"home" | "result" | "history">("home");
const latestItinerary = ref<Itinerary | null>(null);

function handleGenerated(itinerary: Itinerary) {
  latestItinerary.value = itinerary;
  currentView.value = "result";
}

function openTrip(itinerary: Itinerary) {
  latestItinerary.value = itinerary;
  currentView.value = "result";
}

function updateCurrentItinerary(itinerary: Itinerary) {
  latestItinerary.value = itinerary;
  currentView.value = "result";
}
</script>

<template>
  <div class="app-shell">
    <div class="app-shell__glow app-shell__glow--left"></div>
    <div class="app-shell__glow app-shell__glow--right"></div>

    <header class="hero">
      <div class="hero__brand">
        <span class="hero__logo">云</span>
        <span>云途 AI</span>
      </div>
      <h1 class="hero__title">你好，今天想去哪里？</h1>
      <p class="hero__subtitle">说出你的旅行灵感，我来把它变成一份真正好用的行程</p>

      <div class="hero__tabs">
        <button
          :class="['hero__tab', { 'hero__tab--active': currentView === 'home' }]"
          @click="currentView = 'home'"
        >
          AI 助手
        </button>
        <button
          :class="[
            'hero__tab',
            { 'hero__tab--active': currentView === 'result' },
            { 'hero__tab--disabled': !latestItinerary }
          ]"
          :disabled="!latestItinerary"
          @click="currentView = 'result'"
        >
          我的行程
        </button>
        <button
          :class="['hero__tab', { 'hero__tab--active': currentView === 'history' }]"
          @click="currentView = 'history'"
        >
          历史旅行
        </button>
      </div>
    </header>

    <main class="page-content">
      <Home
        v-if="currentView === 'home'"
        @generated="handleGenerated"
      />
      <Result
        v-else-if="currentView === 'result'"
        :itinerary="latestItinerary"
        @back-home="currentView = 'home'"
        @view-history="currentView = 'history'"
        @updated="updateCurrentItinerary"
      />
      <History
        v-else
        :active="currentView === 'history'"
        @open-trip="openTrip"
      />
    </main>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  min-width: 320px;
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at top left, rgba(199, 215, 255, 0.65), transparent 30%),
    radial-gradient(circle at right 18%, rgba(216, 199, 255, 0.42), transparent 22%),
    linear-gradient(180deg, #f3f6fc 0%, #edf1f7 100%);
  color: #1f2937;
}

:global(*) {
  box-sizing: border-box;
}

.app-shell {
  position: relative;
  min-height: 100vh;
  padding: 26px 24px 64px;
  overflow: hidden;
}

.app-shell__glow {
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  filter: blur(24px);
  opacity: 0.5;
  pointer-events: none;
}

.app-shell__glow--left {
  top: -110px;
  left: -90px;
  background: rgba(113, 132, 255, 0.45);
}

.app-shell__glow--right {
  right: -80px;
  bottom: 120px;
  background: rgba(155, 116, 255, 0.25);
}

.hero {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  margin: 0 auto 26px;
  text-align: center;
}

.hero__brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: rgba(255,255,255,.94);
  font-size: 14px;
  font-weight: 800;
  letter-spacing: .08em;
}

.hero__logo {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  color: #6873d4;
  background: rgba(255,255,255,.92);
  box-shadow: 0 8px 20px rgba(35,42,102,.2);
}

.hero__title {
  margin: 13px 0 0;
  color: #ffffff;
  font-size: 38px;
  line-height: 1.1;
}

.hero__subtitle {
  margin: 8px 0 0;
  color: rgba(255,255,255,.72);
  font-size: 14px;
}

.hero::before {
  content: "";
  position: absolute;
  inset: -26px 0 auto;
  height: 225px;
  z-index: -1;
  border-radius: 0 0 38px 38px;
  background: linear-gradient(125deg, #526fd1 0%, #696ccf 50%, #815bc2 100%);
  box-shadow: 0 32px 80px rgba(95, 110, 172, 0.3);
}

.hero__tabs {
  display: inline-flex;
  gap: 10px;
  margin-top: 18px;
  padding: 6px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(10px);
}

.hero__tab {
  border: none;
  border-radius: 12px;
  padding: 8px 17px;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.hero__tab--active {
  background: rgba(255, 255, 255, 0.92);
  color: #5f60c8;
}

.hero__tab--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-content {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  margin: 0 auto;
}

@media (max-width: 768px) {
  .app-shell {
    padding: 24px 16px 40px;
  }

  .hero__title {
    font-size: 34px;
  }

  .hero::before {
    inset: -20px 0 auto;
    height: 230px;
  }
}
</style>
