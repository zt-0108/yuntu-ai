<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { message } from "ant-design-vue";

import AmapTripMap from "../components/AmapTripMap.vue";
import {
  editTrip,
  fetchWeatherForecast,
  getMarkdownExportUrl,
  getPdfExportUrl,
  saveTrip,
} from "../services/api";
import type { Itinerary, WeatherForecastResponse } from "../types";

const props = defineProps<{
  itinerary: Itinerary | null;
}>();

const emit = defineEmits<{
  backHome: [];
  viewHistory: [];
  updated: [itinerary: Itinerary];
}>();

const saving = ref(false);
const exportingPdf = ref(false);
const exportingMarkdown = ref(false);
const editing = ref(false);
const editScope = ref("day_1");
const editInstruction = ref("这一天节奏更轻松一点，减少固定安排。");
const weatherLoading = ref(false);
const weatherError = ref("");
const weather = ref<WeatherForecastResponse | null>(null);

function formatShortDate(dateText?: string | null): string {
  if (!dateText) {
    return "待定";
  }

  const parts = dateText.split("-");
  if (parts.length !== 3) {
    return dateText;
  }

  return `${parts[1]}-${parts[2]}`;
}

function formatRailPrice(value?: number | null): string {
  return value == null ? "价格待查" : `¥${value.toFixed(0)}`;
}

function formatWeatherDate(dateText?: string | null, week?: string | null): string {
  const weekdayMap: Record<string, string> = {
    "1": "周一",
    "2": "周二",
    "3": "周三",
    "4": "周四",
    "5": "周五",
    "6": "周六",
    "7": "周日",
  };
  const weekday = week ? weekdayMap[week] || `周${week}` : "";
  return [formatShortDate(dateText), weekday].filter(Boolean).join(" ");
}

const budgetItems = computed(() => {
  if (!props.itinerary) {
    return [];
  }

  const budget = props.itinerary.budget_breakdown;
  return [
    { label: "景点门票", value: `¥${budget.tickets.toFixed(0)}` },
    { label: "酒店住宿", value: `¥${budget.hotel.toFixed(0)}` },
    { label: "餐饮费用", value: `¥${budget.meals.toFixed(0)}` },
    { label: "交通费用", value: `¥${budget.transport.toFixed(0)}` },
  ];
});

const dayBudgetItems = computed(() => {
  if (!props.itinerary) {
    return [];
  }

  return props.itinerary.days.map((day) => {
    const tickets = day.spots.reduce((sum, spot) => sum + (spot.estimated_cost ?? 0), 0);
    const meals = day.meals.reduce((sum, meal) => sum + (meal.estimated_cost ?? 0), 0);
    const transport = day.transport.reduce((sum, item) => sum + (item.estimated_cost ?? 0), 0);
    const hotel = day.hotel?.estimated_cost ?? 0;
    const total = tickets + meals + transport + hotel;

    return {
      key: day.day_index,
      title: `第${day.day_index}天`,
      subtitle: day.theme || "未命名主题",
      tickets,
      meals,
      transport,
      hotel,
      total,
    };
  });
});

const mapPoints = computed(() => {
  if (!props.itinerary) {
    return [];
  }

  return props.itinerary.days.flatMap((day) =>
    day.spots.map((spot) => ({
      key: `${day.day_index}-${spot.name}`,
      dayIndex: day.day_index,
      date: day.date || "待定",
      theme: day.theme || "未命名主题",
      name: spot.name,
      address: spot.address || spot.location || "待补充",
      latitude: spot.latitude,
      longitude: spot.longitude,
      poiId: spot.poi_id,
      imageUrl: spot.image_url,
      description: spot.description || "暂无说明",
    }))
  );
});

const technicalTipKeywords = [
  "LLM",
  "RAG",
  "LangChain",
  "Chroma",
  "演示",
  "测试",
  "规则",
  "模型",
  "源码",
];

const rainWeatherKeywords = ["雨", "阵雨", "雷阵雨", "小雨", "中雨", "大雨"];
const sunnyTipKeywords = ["防晒", "太阳", "日照", "晒"];

const weatherText = computed(() => {
  if (!weather.value) {
    return "";
  }

  return weather.value.days
    .map((day) => `${day.day_weather || ""}${day.night_weather || ""}`)
    .join(" ");
});

const hasRainyWeather = computed(() => {
  return rainWeatherKeywords.some((keyword) => weatherText.value.includes(keyword));
});

const displayTips = computed(() => {
  if (!props.itinerary) {
    return [];
  }

  const tips = props.itinerary.tips
    .map((tip) => tip.trim())
    .filter(Boolean)
    .filter((tip) => !technicalTipKeywords.some((keyword) => tip.includes(keyword)));

  const weatherAwareTips = hasRainyWeather.value
    ? tips.filter((tip) => !sunnyTipKeywords.some((keyword) => tip.includes(keyword)))
    : tips;

  if (hasRainyWeather.value) {
    weatherAwareTips.push("天气可能有雨，建议随身带伞或轻便雨衣。");
    weatherAwareTips.push("阴雨天路面湿滑，步行游览时建议穿舒适防滑的鞋子。");
  }

  const uniqueTips = Array.from(new Set(weatherAwareTips));
  if (uniqueTips.length) {
    return uniqueTips;
  }

  return [
    `建议根据${props.itinerary.destination}当天实时天气准备雨具或薄外套。`,
    "当天如果步行游览较多，建议选择舒适防滑的鞋子，并根据体力调整停留时间。",
  ];
});

const provenanceItems = computed(() => {
  const provenance = props.itinerary?.provenance;
  const destination = props.itinerary?.destination || "该目的地";
  if (!provenance) {
    return [
      {
        key: "legacy",
        icon: "◌",
        label: "来源记录",
        value: "历史行程",
        detail: "该行程生成时尚未记录结构化来源信息。",
        tone: "neutral",
      },
    ];
  }

  const planningText = {
    llm_with_rag: ["AI + 本地攻略", "模型结合本地知识库片段生成行程。"],
    llm_general_knowledge: ["AI 通用知识", `知识库暂无${destination}资料，行程由模型通用知识生成。`],
    rule_fallback: ["规则兜底", "模型调用未成功，本次使用本地规则生成基础行程。"],
    unknown: ["来源未知", "当前行程没有记录规划来源。"],
  }[provenance.planning_source];

  const ragText = provenance.rag_status === "matched"
    ? [`命中 ${provenance.rag_context_count} 条`, `已使用${destination}本地攻略片段。`, "success"]
    : provenance.rag_status === "unavailable"
      ? ["暂无匹配资料", `本地知识库没有可用的${destination}攻略片段。`, "warning"]
      : ["状态未知", "没有记录本地知识库命中情况。", "neutral"];

  const mapText = provenance.map_status === "verified"
    ? [`${provenance.map_verified_spots}/${provenance.map_total_spots} 已匹配`, "全部景点已获得高德地点信息。", "success"]
    : provenance.map_status === "partial"
      ? [`${provenance.map_verified_spots}/${provenance.map_total_spots} 已匹配`, "部分景点已获得高德地点信息，请复核其余地点。", "warning"]
      : provenance.map_status === "disabled"
        ? ["未启用", "本次没有调用高德地图增强。", "neutral"]
        : ["未匹配", "暂未获得可靠的高德地点信息。", "warning"];

  const railText = provenance.rail_status === "available"
    ? ["已查询", "已获取往返候选车次；余票与票价请以铁路12306官方渠道为准。", "success"]
    : provenance.rail_status === "disabled"
      ? ["未启用", "填写出发城市且启用铁路 MCP 后可查询候选车次。", "neutral"]
      : provenance.rail_status === "error"
        ? ["暂不可用", "铁路查询失败，但不影响本次行程内容。", "warning"]
        : ["暂无车次", "当前筛选条件下没有匹配的候选车次。", "warning"];

  return [
    { key: "planning", icon: "AI", label: "规划来源", value: planningText[0], detail: planningText[1], tone: provenance.planning_source === "rule_fallback" ? "warning" : "success" },
    { key: "rag", icon: "R", label: "本地知识", value: ragText[0], detail: ragText[1], tone: ragText[2] },
    { key: "map", icon: "⌖", label: "地图核验", value: mapText[0], detail: mapText[1], tone: mapText[2] },
    { key: "rail", icon: "🚄", label: "铁路车次", value: railText[0], detail: railText[1], tone: railText[2] },
    { key: "budget", icon: "¥", label: "费用信息", value: "估算值", detail: "门票、住宿、餐饮和交通费用仅供规划参考，请以下单时价格为准。", tone: "neutral" },
  ];
});

function buildVisibleItinerary(): Itinerary | null {
  if (!props.itinerary) {
    return null;
  }

  return {
    ...props.itinerary,
    tips: displayTips.value,
  };
}

async function loadWeather() {
  if (!props.itinerary?.destination) {
    weather.value = null;
    return;
  }

  weatherLoading.value = true;
  weatherError.value = "";
  try {
    weather.value = await fetchWeatherForecast(props.itinerary.destination);
  } catch (error) {
    console.error(error);
    weather.value = null;
    weatherError.value = "天气信息加载失败。";
  } finally {
    weatherLoading.value = false;
  }
}

watch(
  () => props.itinerary?.destination,
  () => {
    void loadWeather();
  },
  { immediate: true }
);

watch(
  () => props.itinerary?.trip_id,
  () => {
    const firstDay = props.itinerary?.days[0];
    editScope.value = firstDay ? `day_${firstDay.day_index}` : "day_1";
  },
  { immediate: true }
);

async function openPdfExport() {
  const itineraryToExport = buildVisibleItinerary();
  if (!itineraryToExport) {
    return;
  }

  const exportWindow = window.open("about:blank", "_blank");
  exportingPdf.value = true;
  try {
    await saveTrip(itineraryToExport);
    const exportUrl = getPdfExportUrl(itineraryToExport.trip_id);
    if (exportWindow) {
      exportWindow.location.href = exportUrl;
    } else {
      window.location.href = exportUrl;
    }
  } catch (error) {
    console.error(error);
    exportWindow?.close();
    message.error("导出 PDF 前同步当前行程失败。");
  } finally {
    exportingPdf.value = false;
  }
}

async function openMarkdownExport() {
  const itineraryToExport = buildVisibleItinerary();
  if (!itineraryToExport) {
    return;
  }

  const exportWindow = window.open("about:blank", "_blank");
  exportingMarkdown.value = true;
  try {
    await saveTrip(itineraryToExport);
    const exportUrl = getMarkdownExportUrl(itineraryToExport.trip_id);
    if (exportWindow) {
      exportWindow.location.href = exportUrl;
    } else {
      window.location.href = exportUrl;
    }
  } catch (error) {
    console.error(error);
    exportWindow?.close();
    message.error("导出 Markdown 前同步当前行程失败。");
  } finally {
    exportingMarkdown.value = false;
  }
}

async function handleSave() {
  const itineraryToSave = buildVisibleItinerary();
  if (!itineraryToSave) {
    return;
  }

  saving.value = true;
  try {
    await saveTrip(itineraryToSave);
    message.success("行程已保存，可以去历史列表查看。");
  } catch (error) {
    console.error(error);
    message.error("保存行程失败。");
  } finally {
    saving.value = false;
  }
}

async function handleEdit() {
  if (!props.itinerary) {
    return;
  }

  const instruction = editInstruction.value.trim();
  if (!instruction) {
    message.warning("请先输入想如何调整行程。");
    return;
  }

  editing.value = true;
  try {
    const updatedItinerary = await editTrip({
      trip_id: props.itinerary.trip_id,
      current_itinerary: props.itinerary,
      user_instruction: instruction,
      edit_scope: editScope.value,
      preserve_constraints: ["保留预算结构", "保留目的地和旅行日期"],
    });
    emit("updated", updatedItinerary);
    message.success("行程已智能调整。");
  } catch (error) {
    console.error(error);
    message.error("智能调整失败，请稍后再试。");
  } finally {
    editing.value = false;
  }
}
</script>

<template>
  <section v-if="itinerary" class="result-page">
    <header class="trip-hero">
      <div class="trip-hero__copy">
        <div class="trip-hero__eyebrow">AI TRIP BOARD · {{ itinerary.days.length }} DAYS</div>
        <h2>{{ itinerary.destination }}，准备出发</h2>
        <p>{{ itinerary.summary }}</p>
        <div class="trip-hero__meta">
          <span>📅 {{ itinerary.days[0]?.date || "日期待定" }} — {{ itinerary.days[itinerary.days.length - 1]?.date || "日期待定" }}</span>
          <span>💰 预计 ¥{{ itinerary.estimated_budget.toFixed(0) }}</span>
          <span>📍 {{ mapPoints.length }} 个目的地点位</span>
        </div>
      </div>
      <div class="trip-hero__stamp"><strong>{{ itinerary.days.length }}</strong><small>DAYS</small></div>
    </header>

    <nav class="action-dock" aria-label="行程操作">
      <button class="back-button" @click="$emit('backHome')">← 继续和助手聊</button>
      <div class="action-dock__right">
        <button class="save-button" :disabled="saving" @click="handleSave">
          {{ saving ? "收藏中..." : "♡ 收藏行程" }}
        </button>
        <button class="history-button" @click="$emit('viewHistory')">旅行收藏夹</button>
        <button class="export-button" :disabled="exportingPdf" @click="openPdfExport">
          {{ exportingPdf ? "准备 PDF..." : "下载手册" }}
        </button>
        <button
          class="export-button export-button--light"
          :disabled="exportingMarkdown"
          @click="openMarkdownExport"
        >
          {{ exportingMarkdown ? "准备中..." : "导出文本" }}
        </button>
      </div>
    </nav>

    <div class="result-grid">
      <section v-if="itinerary.rail_tickets" class="result-card result-card--full rail-card">
        <div class="result-card__title"><span>🚄</span> 往返车票建议</div>
        <div v-if="itinerary.rail_tickets.status === 'available'" class="rail-directions">
          <div
            v-for="direction in [{ key: 'outbound', label: '去程', items: itinerary.rail_tickets.outbound }, { key: 'return', label: '返程', items: itinerary.rail_tickets.return_trip }]"
            :key="direction.key"
            class="rail-direction"
          >
            <h3>{{ direction.label }} · {{ direction.items[0]?.travel_date || "日期待定" }}</h3>
            <div v-if="direction.items.length" class="rail-options">
              <article v-for="train in direction.items" :key="`${direction.key}-${train.train_code}`" class="rail-option">
                <div class="rail-option__head"><strong>{{ train.train_code }}</strong><span>{{ train.duration }}</span></div>
                <div class="rail-option__route">
                  <div><b>{{ train.departure_time }}</b><span>{{ train.departure_station }}</span></div>
                  <div class="rail-option__line">→</div>
                  <div><b>{{ train.arrival_time }}</b><span>{{ train.arrival_station }}</span></div>
                </div>
                <div class="rail-option__seat">
                  <span>{{ train.preferred_seat || "席别" }}：{{ train.preferred_seat_availability || "待查" }}</span>
                  <strong>{{ formatRailPrice(train.preferred_seat_price) }}</strong>
                </div>
              </article>
            </div>
            <p v-else class="rail-empty">当前偏好下未找到{{ direction.label }}候选车次。</p>
          </div>
        </div>
        <div v-else class="rail-empty">{{ itinerary.rail_tickets.message || "暂未获得候选车次。" }}</div>
        <div class="rail-disclaimer">
          {{ itinerary.rail_tickets.disclaimer }}
          <a :href="itinerary.rail_tickets.source_url" target="_blank" rel="noopener noreferrer">数据接口说明</a>
        </div>
      </section>

      <section class="result-card overview-card">
        <div class="result-card__title"><span>✦</span> 出发前提醒</div>
        <div v-if="displayTips.length" class="overview-tips">
          <ul>
            <li v-for="tip in displayTips" :key="tip">{{ tip }}</li>
          </ul>
        </div>
      </section>

      <section class="result-card">
        <div class="result-card__title"><span>¥</span> 预算分配</div>
        <div class="budget-grid">
          <div v-for="item in budgetItems" :key="item.label" class="budget-box">
            <div class="budget-box__label">{{ item.label }}</div>
            <div class="budget-box__value">{{ item.value }}</div>
          </div>
        </div>
        <div class="budget-total">
          <span>预估总费用</span>
          <strong>¥{{ itinerary.estimated_budget.toFixed(0) }}</strong>
        </div>
      </section>

      <section class="result-card result-card--full provenance-card">
        <div class="result-card__title"><span>✓</span> 信息来源与可信度</div>
        <div class="provenance-grid">
          <article
            v-for="item in provenanceItems"
            :key="item.key"
            class="provenance-item"
            :class="`provenance-item--${item.tone}`"
          >
            <div class="provenance-item__icon">{{ item.icon }}</div>
            <div>
              <div class="provenance-item__label">{{ item.label }}</div>
              <strong>{{ item.value }}</strong>
              <p>{{ item.detail }}</p>
            </div>
          </article>
        </div>
      </section>

      <section class="result-card result-card--map">
        <div class="result-card__title"><span>⌖</span> 路线地图</div>
        <AmapTripMap :points="mapPoints" />
      </section>

      <section class="result-card result-card--weather">
        <div class="result-card__title"><span>☼</span> 旅途天气</div>

        <div v-if="weatherLoading" class="weather-state">正在加载天气信息...</div>
        <div v-else-if="weatherError" class="weather-state">{{ weatherError }}</div>
        <div v-else-if="weather" class="weather-grid">
          <article
            v-for="day in weather.days"
            :key="`${day.date}-${day.week}`"
            class="weather-card"
          >
            <div class="weather-card__date">
              {{ formatWeatherDate(day.date, day.week) }}
            </div>
            <div class="weather-card__temp">
              {{ day.day_temp || "-" }}° / {{ day.night_temp || "-" }}°
            </div>
            <div class="weather-card__desc">白天：{{ day.day_weather || "未知" }}</div>
            <div class="weather-card__desc">夜间：{{ day.night_weather || "未知" }}</div>
          </article>
        </div>
        <div v-else class="weather-state">暂无天气信息。</div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title"><span>✦</span> 让助手帮我调整</div>
        <div class="edit-panel">
          <div class="edit-panel__controls">
            <label class="edit-field">
              <span>调整范围</span>
              <select v-model="editScope">
                <option
                  v-for="day in itinerary.days"
                  :key="day.day_index"
                  :value="`day_${day.day_index}`"
                >
                  第{{ day.day_index }}天 · {{ day.theme || "未命名主题" }}
                </option>
              </select>
            </label>
            <button
              class="edit-submit-button"
              :disabled="editing"
              @click="handleEdit"
            >
              {{ editing ? "正在重新规划..." : "提交给旅行助手" }}
            </button>
          </div>
          <textarea
            v-model="editInstruction"
            class="edit-textarea"
            rows="3"
            placeholder="例如：第二天轻松一点，不要安排太满；第三天想换成适合看日落的地点。"
          ></textarea>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title"><span>◫</span> 每日花费预览</div>
        <div class="day-budget-grid">
          <article
            v-for="item in dayBudgetItems"
            :key="item.key"
            class="day-budget-card"
          >
            <div class="day-budget-card__header">
              <span>{{ item.title }}</span>
              <span>{{ item.subtitle }}</span>
            </div>
            <div class="day-budget-card__body">
              <div class="day-budget-row">
                <span>门票</span>
                <strong>¥{{ item.tickets.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>餐饮</span>
                <strong>¥{{ item.meals.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>交通</span>
                <strong>¥{{ item.transport.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>住宿</span>
                <strong>¥{{ item.hotel.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row day-budget-row--total">
                <span>当日合计</span>
                <strong>¥{{ item.total.toFixed(0) }}</strong>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title"><span>⌖</span> 值得停留的地方</div>
        <div class="point-grid">
          <article v-for="point in mapPoints" :key="point.key" class="point-card">
            <div class="point-card__header">
              <span>第{{ point.dayIndex }}天 · {{ point.name }}</span>
              <span>{{ formatShortDate(point.date) }}</span>
            </div>

            <div class="point-card__body">
              <div
                v-if="point.imageUrl"
                class="point-card__image"
                :style="{ backgroundImage: `url(${point.imageUrl})` }"
              ></div>
              <div v-else class="point-card__image point-card__image--empty">
                暂无景点图片
              </div>
              <div class="point-card__line">
                <strong>主题：</strong>
                <span>{{ point.theme }}</span>
              </div>
              <div class="point-card__line">
                <strong>地址：</strong>
                <span>{{ point.address }}</span>
              </div>
              <div class="point-card__desc">{{ point.description }}</div>
            </div>
          </article>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title"><span>☷</span> 每日行程单</div>
        <div class="day-list">
          <details
            v-for="day in itinerary.days"
            :key="day.day_index"
            class="day-card"
            :open="day.day_index === 1"
          >
            <summary class="day-card__header">
              <span>第{{ day.day_index }}天 · {{ day.theme || "未命名主题" }}</span>
              <span class="day-card__meta">{{ formatShortDate(day.date) }}</span>
            </summary>

            <div class="day-card__body">
              <div
                v-for="(spot, index) in day.spots"
                :key="`spot-${index}`"
                class="day-card__section"
              >
                <strong>{{ day.spots.length > 1 ? `景点${index + 1}：` : "主要景点：" }}</strong>
                <span>{{ spot.name || "未安排" }}</span>
                <div v-if="spot.address || spot.location" class="day-card__subline">
                  地址：{{ spot.address || spot.location }}
                </div>
                <div v-if="spot.description" class="day-card__subline">
                  {{ spot.description }}
                </div>
              </div>

              <div
                v-for="(meal, index) in day.meals"
                :key="`meal-${index}`"
                class="day-card__section"
              >
                <strong>{{ meal.meal_type ? `${meal.meal_type}：` : "餐饮建议：" }}</strong>
                <span>{{ meal.name || "未安排" }}</span>
                <div v-if="meal.notes" class="day-card__subline">{{ meal.notes }}</div>
              </div>

              <div class="day-card__section">
                <strong>住宿安排：</strong>
                <span>{{ day.hotel?.name || "未安排" }}</span>
              </div>
              <div class="day-card__section">
                <strong>交通信息：</strong>
                <span>
                  {{
                    day.transport[0]?.distance_km != null
                      ? `${day.transport[0].distance_km.toFixed(2)} km / ${day.transport[0].estimated_minutes ?? 0} 分钟`
                      : day.transport[0]?.duration || "待补充"
                  }}
                </span>
              </div>
              <div class="day-card__section">
                <strong>备注：</strong>
                <span>{{ day.notes[day.notes.length - 1] || "无" }}</span>
              </div>
            </div>
          </details>
        </div>
      </section>
    </div>
  </section>

  <section v-else class="empty-state">
    <div class="empty-state__card">
      <div class="empty-state__icon">🗺️</div>
      <h2>旅程还没有开始</h2>
      <p>先和云途旅行助手聊聊你的想法，我们会把灵感整理成完整方案。</p>
      <button class="back-button" @click="$emit('backHome')">去找旅行助手</button>
    </div>
  </section>
</template>

<style scoped>
.result-page {
  display: grid;
  gap: 18px;
}

.result-card,
.empty-state__card {
  border: 1px solid rgba(117, 128, 156, 0.12);
  border-radius: 23px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 45px rgba(61, 75, 111, 0.09);
  backdrop-filter: blur(14px);
}

.trip-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 240px;
  padding: 34px 40px;
  overflow: hidden;
  border-radius: 28px;
  color: #fff;
  background:
    radial-gradient(circle at 86% 22%, rgba(255,255,255,.2), transparent 18%),
    linear-gradient(125deg, #354f92 0%, #5d63bd 58%, #7c58ad 100%);
  box-shadow: 0 25px 58px rgba(58, 69, 139, .24);
}

.trip-hero::after {
  content: "";
  position: absolute;
  right: -40px;
  bottom: -95px;
  width: 300px;
  height: 300px;
  border: 40px solid rgba(255,255,255,.06);
  border-radius: 50%;
}

.trip-hero__copy { position: relative; z-index: 1; max-width: 820px; }
.trip-hero__eyebrow { margin-bottom: 10px; color: rgba(255,255,255,.62); font-size: 10px; font-weight: 900; letter-spacing: .18em; }
.trip-hero h2 { margin: 0; font-size: 36px; line-height: 1.2; }
.trip-hero p { max-width: 760px; margin: 12px 0 20px; color: rgba(255,255,255,.76); line-height: 1.75; }
.trip-hero__meta { display: flex; flex-wrap: wrap; gap: 9px; }
.trip-hero__meta span { padding: 7px 10px; border: 1px solid rgba(255,255,255,.13); border-radius: 999px; background: rgba(255,255,255,.09); font-size: 11px; }
.trip-hero__stamp { position: relative; z-index: 1; display: grid; flex: 0 0 auto; place-items: center; width: 104px; height: 104px; margin-left: 30px; border: 1px solid rgba(255,255,255,.25); border-radius: 50%; background: rgba(255,255,255,.1); backdrop-filter: blur(8px); }
.trip-hero__stamp strong { margin-bottom: -23px; font-size: 38px; }
.trip-hero__stamp small { color: rgba(255,255,255,.62); font-size: 9px; letter-spacing: .18em; }

.action-dock { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid rgba(117,128,156,.12); border-radius: 19px; background: rgba(255,255,255,.93); box-shadow: 0 12px 34px rgba(61,75,111,.07); }
.action-dock__right { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }

.result-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 17px;
  padding: 2px 1px 13px;
  border-bottom: 1px solid #edf0f5;
  color: #344054;
  font-size: 15px;
  font-weight: 800;
}

.back-button,
.save-button,
.history-button,
.export-button {
  width: auto;
  border: none;
  border-radius: 14px;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.back-button {
  flex: 0 0 auto;
  background: rgba(109, 130, 222, 0.12);
  color: #5d66c3;
}

.save-button {
  background: linear-gradient(135deg, #7386e0 0%, #8f71d8 100%);
  color: #ffffff;
}

.save-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.export-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.history-button {
  background: rgba(79, 70, 229, 0.1);
  color: #5b5bd6;
}

.export-button {
  background: rgba(59, 130, 246, 0.12);
  color: #3568d4;
}

.export-button--light {
  background: rgba(16, 185, 129, 0.12);
  color: #0f8c63;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.result-card {
  padding: 21px;
}

.result-card--map,
.result-card--weather {
  min-height: 330px;
}

.result-card--full {
  grid-column: 1 / -1;
}

.info-row {
  margin-bottom: 10px;
  color: #475467;
  line-height: 1.7;
}

.summary-text {
  margin-top: 14px;
}

.overview-tips {
  margin-top: 0;
  padding: 14px 16px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(109, 130, 222, 0.08), rgba(138, 103, 207, 0.08));
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.overview-tips__title {
  margin-bottom: 8px;
  color: #465467;
  font-weight: 800;
}

.overview-tips ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
  color: #5d6675;
  line-height: 1.7;
}

.provenance-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.provenance-item {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 11px;
  padding: 15px;
  border: 1px solid rgba(98, 116, 164, 0.1);
  border-radius: 16px;
  background: #f8faff;
}

.provenance-item__icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 12px;
  background: #e9edff;
  color: #5664be;
  font-size: 12px;
  font-weight: 900;
}

.provenance-item__label {
  margin-bottom: 3px;
  color: #667085;
  font-size: 12px;
}

.provenance-item strong {
  color: #344054;
  font-size: 15px;
}

.provenance-item p {
  margin: 5px 0 0;
  color: #667085;
  font-size: 12px;
  line-height: 1.55;
}

.provenance-item--success .provenance-item__icon {
  background: #e7f7ef;
  color: #14845f;
}

.provenance-item--warning .provenance-item__icon {
  background: #fff3dc;
  color: #b56a12;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.budget-box {
  padding: 16px;
  border-radius: 16px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.budget-box__label {
  color: #667085;
  font-size: 13px;
}

.budget-box__value {
  margin-top: 10px;
  color: #3b82f6;
  font-size: 22px;
  font-weight: 700;
}

.budget-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(135deg, #7386e0 0%, #8f71d8 100%);
  color: #ffffff;
}

.budget-total strong {
  font-size: 28px;
}

.weather-state {
  color: #667085;
  line-height: 1.8;
}

.weather-grid {
  display: grid;
  gap: 12px;
}

.weather-card {
  padding: 14px;
  border-radius: 16px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.weather-card__date {
  color: #465467;
  font-weight: 700;
}

.weather-card__temp {
  margin: 8px 0;
  color: #3b82f6;
  font-size: 24px;
  font-weight: 800;
}

.weather-card__desc {
  color: #667085;
  line-height: 1.7;
}

.edit-panel {
  display: grid;
  gap: 14px;
}

.edit-panel__controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 12px;
  align-items: end;
}

.edit-field {
  display: grid;
  gap: 8px;
  color: #465467;
  font-weight: 700;
}

.edit-field select,
.edit-textarea {
  width: 100%;
  border: 1px solid rgba(98, 116, 164, 0.18);
  border-radius: 14px;
  background: #fbfcff;
  color: #334155;
  font: inherit;
  outline: none;
}

.edit-field select {
  min-height: 44px;
  padding: 0 14px;
}

.edit-textarea {
  resize: vertical;
  min-height: 92px;
  padding: 12px 14px;
  line-height: 1.7;
}

.edit-field select:focus,
.edit-textarea:focus {
  border-color: rgba(109, 130, 222, 0.65);
  box-shadow: 0 0 0 3px rgba(109, 130, 222, 0.12);
}

.edit-submit-button {
  min-height: 44px;
  border: none;
  border-radius: 14px;
  background: linear-gradient(135deg, #7386e0 0%, #8f71d8 100%);
  color: #ffffff;
  font-weight: 800;
  cursor: pointer;
}

.edit-submit-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.day-budget-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.day-budget-card {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
}

.day-budget-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(109, 130, 222, 0.08);
  color: #465467;
  font-weight: 700;
}

.day-budget-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.day-budget-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #475467;
}

.day-budget-row--total {
  padding-top: 10px;
  border-top: 1px solid rgba(98, 116, 164, 0.08);
  color: #2f4fa5;
}

.rail-directions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.rail-direction h3 { margin: 0 0 12px; color: #344054; font-size: 15px; }
.rail-options { display: grid; gap: 10px; }
.rail-option { padding: 14px; border: 1px solid #e5e9f2; border-radius: 16px; background: #fbfcff; }
.rail-option__head, .rail-option__seat { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.rail-option__head strong { color: #4e63c9; font-size: 18px; }
.rail-option__head span, .rail-option__seat { color: #667085; font-size: 12px; }
.rail-option__route { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; align-items: center; margin: 14px 0; text-align: center; }
.rail-option__route div:not(.rail-option__line) { display: grid; gap: 3px; }
.rail-option__route b { color: #263248; font-size: 20px; }
.rail-option__route span { color: #667085; font-size: 12px; }
.rail-option__line { color: #8794d8; }
.rail-option__seat strong { color: #d65d35; font-size: 15px; }
.rail-empty { padding: 18px; border-radius: 14px; color: #667085; background: #f7f8fb; }
.rail-disclaimer { margin-top: 14px; color: #8a93a3; font-size: 12px; line-height: 1.7; }
.rail-disclaimer a { margin-left: 8px; color: #5b6dcc; }

.point-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.point-card {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
}

.point-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(109, 130, 222, 0.08);
  color: #465467;
  font-weight: 700;
}

.point-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.point-card__image {
  min-height: 150px;
  border-radius: 14px;
  background-position: center;
  background-size: cover;
  background-color: #eef3ff;
}

.point-card__image--empty {
  display: grid;
  place-items: center;
  color: #7b8494;
  font-weight: 700;
  background:
    linear-gradient(135deg, rgba(129, 179, 255, 0.18), rgba(137, 108, 230, 0.15)),
    #f7f9ff;
}

.point-card__line {
  color: #475467;
  line-height: 1.7;
}

.point-card__desc {
  padding-top: 10px;
  border-top: 1px solid rgba(98, 116, 164, 0.08);
  color: #667085;
  line-height: 1.7;
}

.day-list {
  display: grid;
  gap: 12px;
}

.day-card {
  border-radius: 18px;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
  overflow: hidden;
}

.day-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(109, 130, 222, 0.08);
  color: #465467;
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}

.day-card__header::-webkit-details-marker {
  display: none;
}

.day-card__header::after {
  content: "展开";
  flex: 0 0 auto;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(109, 130, 222, 0.12);
  color: #5b5bd6;
  font-size: 12px;
}

.day-card[open] .day-card__header::after {
  content: "收起";
}

.day-card__meta {
  margin-left: auto;
  color: #667085;
  font-size: 13px;
}

.day-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.day-card__section {
  color: #475467;
  line-height: 1.7;
}

.day-card__subline {
  margin-top: 4px;
  padding-left: 8px;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 360px;
}

.empty-state__card {
  max-width: 560px;
  padding: 36px;
  text-align: center;
}

.empty-state__icon { margin-bottom: 10px; font-size: 48px; }

.empty-state__card h2 {
  margin: 0 0 12px;
}

.empty-state__card p {
  margin: 0 0 18px;
  color: #667085;
  line-height: 1.7;
}

@media (max-width: 960px) {
  .result-grid {
    grid-template-columns: 1fr;
  }

  .edit-panel__controls {
    grid-template-columns: 1fr;
  }

  .trip-hero { min-height: 210px; padding: 28px; }
  .trip-hero h2 { font-size: 30px; }
  .trip-hero__stamp { width: 82px; height: 82px; }
  .action-dock { align-items: stretch; flex-direction: column; }
  .action-dock__right { display: grid; grid-template-columns: repeat(2,1fr); }
  .action-dock button { width: 100%; }
  .rail-directions { grid-template-columns: 1fr; }
}

@media (max-width: 560px) {
  .trip-hero { padding: 24px; }
  .trip-hero__stamp { display: none; }
  .trip-hero h2 { font-size: 27px; }
  .trip-hero__meta { display: grid; }
  .action-dock__right { grid-template-columns: 1fr; }
  .budget-grid { grid-template-columns: 1fr 1fr; }
}
</style>
