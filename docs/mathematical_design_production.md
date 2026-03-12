# Mathematical Design — VRP Trading System (Production)

**Regime-Conditioned Systematic Short Volatility | SPX Options | Python**

> 이 문서는 순수 트레이딩 시스템의 수학적 설계이다.
> 목적: 수익 창출. 연구 요소 없음.
> Options pricing은 Heston + Fourier 단일 경로. PINN, Comparator 없음.
> 별도의 연구 시스템(dual-path + PINN)은 `mathematical_design.md`에 정의.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Layer 0: Variance Risk Premium](#2-layer-0-variance-risk-premium)
3. [Layer 1: Regime Detection](#3-layer-1-regime-detection)
4. [Layer 2: Options Pricing — Heston + Fourier](#4-layer-2-options-pricing)
5. [Layer 3: Strategy Engine](#5-layer-3-strategy-engine)
6. [Layer 4: Risk Management](#6-layer-4-risk-management)
7. [Layer 5: Execution](#7-layer-5-execution)
8. [End-to-End Flow](#8-end-to-end-flow)
9. [Backtest Framework](#9-backtest-framework)
10. [Parameter Reference](#10-parameter-reference)

---

## 1. System Overview

### 1.1 수익의 원천

$$E[R_{\text{total}}] = \underbrace{E[\text{VRP}]}_{\text{structural premium}} + \underbrace{E[\Delta R_{\text{regime}}]}_{\text{risk management}}$$

**Term 1 — Structural VRP:** 옵션 시장에서 implied volatility가 realized volatility를 구조적으로 초과하는 현상. 기관의 hedging mandate에 의해 유지되며, 예측이 아닌 risk bearing의 대가이다.

**Term 2 — Regime Conditioning:** Bear regime에서 exposure를 줄여 drawdown을 축소. 기대수익을 높이는 것이 아니라 geometric mean을 개선:

$$G \approx \bar{r} - \frac{\sigma^2}{2}$$

### 1.2 Architecture

```
┌── Layer 0: VRP Measurement ──────────────────────────────────┐
│  IV (VIX, options chain) → RV (realized vol) → VRP signal    │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 1: Regime Detection ─┴───────────────────────────────┐
│  Market features → HMM (labeling) → XGBoost (real-time)     │
│  Output: p = [P_LowVol, P_NormalVol, P_HighVol]             │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 2: Options Pricing ──┴───────────────────────────────┐
│  Phase 1: Black-Scholes closed-form                          │
│  Phase 2+: Heston + Carr-Madan FFT                           │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 3: Strategy Engine ──┴───────────────────────────────┐
│  Regime probs → position size                                │
│  VRP level → entry/skip                                      │
│  Pricing → strike selection (10-delta put spread)            │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 4: Risk Management ──┴───────────────────────────────┐
│  Vol Scaling → Kelly Ceiling → DD Override                    │
│  min-chain (never multiplicative)                            │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 5: Execution ────────┴───────────────────────────────┐
│  Greeks → order sizing → IBKR                                │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 핵심 설계 원칙

**1. Structural Premium, Not Alpha.** 시장을 이기려 하지 않는다. 구조적으로 존재하는 보험료를 수확한다.

**2. Regime = Risk Management.** Regime detection은 방향 예측이 아니라 "언제 줄일까"를 결정한다.

**3. min-Chain Leverage.** Vol scaling → Kelly ceiling → DD override. $\min(\cdot)$으로 결합, 절대 곱하지 않는다.

**4. Defined Risk.** Put credit spread로 최대 손실이 진입 시점에 확정된다.

---

## 2. Layer 0: Variance Risk Premium

### 2.1 정의

$$\text{VRP}_t = E^{\mathbb{Q}}_t[\sigma^2_{t,t+\tau}] - E^{\mathbb{P}}_t[\sigma^2_{t,t+\tau}]$$

옵션 시장(risk-neutral)이 가격에 반영하는 변동성 > 실제 실현 변동성. 이 차이 = 보험료.

### 2.2 Realized Volatility

$$\text{RV}_t(\tau) = \sqrt{\frac{252}{\tau} \sum_{i=1}^{\tau} r_{t-i}^2}, \quad r_t = \ln(S_t / S_{t-1})$$

### 2.3 VRP 측정

**Phase 1 Proxy (VIX 기반, 무료):**

$$\widehat{\text{VRP}}_t = \frac{\text{VIX}_t^2}{252} - \frac{\text{RV}_t(21)^2}{252}$$

**⚠️ Proxy 한계:** VIX는 향후 30일의 implied vol (forward-looking)이고, RV(21)은 과거 21일의 realized vol (backward-looking)이다. 이 timing mismatch로 인해 proxy VRP는 vol 급변 구간에서 실제 VRP를 왜곡할 수 있다. 이는 Phase 1의 알려진 한계이며, Phase 2에서 동일 시점의 implied vol과 subsequent realized vol을 직접 비교하여 해소된다.

**정규화:**

$$z_{\text{VRP},t} = \frac{\widehat{\text{VRP}}_t - \mu_{\text{VRP}}(252)}{\sigma_{\text{VRP}}(252)}$$

$z > 0$: premium이 평균 이상 → 진입 유리. $z < -1$: premium 이례적 저조 → skip.

**Phase 2 (Options chain 기반):**

실제 SPX chain에서 직접 계산:

$$\text{IV}_{\text{spread}}(K_1, K_2, T) = \sigma_{\text{impl}}(K_1, T) - \text{RV}_t(\tau)$$

### 2.4 VIX Term Structure

$$\text{TS}_t = \frac{\text{VIX3M}_t}{\text{VIX}_t} - 1$$

$\text{TS} > 0$ (contango): 정상. $\text{TS} < 0$ (backwardation): 공포, 주의.

---

## 3. Layer 1: Regime Detection

### 3.1 목적

변동성 환경을 분류하여 short vol position size를 조절한다. 시장 방향 예측이 아니다.

### 3.2 Phase A — 3-State HMM (Labeling)

States: $S = \{\text{Low-Vol}, \text{Normal-Vol}, \text{High-Vol}\}$

**Feature vector:**

$$\mathbf{x}_t = \begin{bmatrix} \sigma_{\text{RV},t}(21) \\ \text{VIX}_t \\ \text{TS}_t \\ \text{VVIX}_t \\ \Delta\text{Vol}_t(5) \end{bmatrix}$$

- $\sigma_{\text{RV}}(21)$: 21일 realized vol
- $\text{VIX}$: CBOE Volatility Index
- $\text{TS}$: VIX term structure
- $\text{VVIX}$: Vol-of-vol
- $\Delta\text{Vol}(5) = (\sigma_{\text{RV}}(5) - \sigma_{\text{RV}}(21)) / \sigma_{\text{RV}}(21)$: 단기 vol 가속도

**HMM Parameters:**

$$\mathbf{x}_t \mid s_t = k \sim \mathcal{N}(\boldsymbol{\mu}_k, \boldsymbol{\Sigma}_k), \quad k \in \{1,2,3\}$$

$$A_{jk} = P(s_t = k \mid s_{t-1} = j)$$

**Baum-Welch (EM) E-step:**

$$\alpha_t(k) = \left[\sum_j \alpha_{t-1}(j) \cdot A_{jk}\right] \cdot \mathcal{N}(\mathbf{x}_t \mid \boldsymbol{\mu}_k, \boldsymbol{\Sigma}_k)$$

$$\gamma_t(k) = \frac{\alpha_t(k) \cdot \beta_t(k)}{\sum_{k'} \alpha_t(k') \cdot \beta_t(k')}$$

**M-step:**

$$\hat{\boldsymbol{\mu}}_k = \frac{\sum_t \gamma_t(k) \mathbf{x}_t}{\sum_t \gamma_t(k)}, \quad \hat{\boldsymbol{\Sigma}}_k = \frac{\sum_t \gamma_t(k)(\mathbf{x}_t - \hat{\boldsymbol{\mu}}_k)(\mathbf{x}_t - \hat{\boldsymbol{\mu}}_k)^\top}{\sum_t \gamma_t(k)}$$

**Training:** Expanding window (min 504d), $n_{\text{init}} = 10$, $n_{\text{iter}} = 200$, full covariance.

**⚠️ Filtering only.** Smoothed probabilities 사용 금지 (미래 정보 포함).

**구현 주의:** `hmmlearn`의 `predict_proba()`와 `score()`는 smoothed posterior $\gamma_t(k) = P(s_t=k \mid \mathbf{x}_{1:T})$를 리턴한다. 실시간에서는 filtered probability $P(s_t=k \mid \mathbf{x}_{1:t})$만 사용해야 한다. 이를 위해 `_do_forward_pass()`로 forward variables $\alpha_t(k)$를 직접 추출하고, $P(s_t=k \mid \mathbf{x}_{1:t}) = \alpha_t(k) / \sum_{k'}\alpha_t(k')$로 정규화해야 한다. 백테스트에서도 동일하게 filtering만 사용 — 이 지점에서 look-ahead bias가 가장 쉽게 유입된다.

### 3.3 Centroid-Anchored Labeling

$$\text{centroid}_k = (\hat{\mu}_{k,\text{RV}}, \hat{\mu}_{k,\text{VIX}})$$

| State | RV | VIX | Action |
|-------|------|------|--------|
| Low-Vol | < 12% | < 15 | Full position |
| Normal-Vol | 12-20% | 15-25 | 기본 position |
| High-Vol | > 20% | > 25 | 축소/중단 |

Refit 후: $\text{label}(k) = \argmin_{c} \| \text{centroid}_k - \text{ref}_c \|_2$

### 3.4 Phase B — XGBoost Real-time

HMM labels → XGBoost target. 현재 features만으로 실시간 추론.

**Output:** $\hat{\mathbf{p}}_t = [P_{\text{LV}}, P_{\text{NV}}, P_{\text{HV}}]$ (CalibratedClassifierCV, isotonic)

**Brier Score:** $\text{BS} = \frac{1}{T}\sum_t\sum_k(p_{t,k} - o_{t,k})^2 < 0.25$

### 3.5 Label Stability

$$\text{Agreement} = \frac{|\{t : \text{new}(t) = \text{old}(t)\}|}{|\text{overlap}|} \geq 0.90$$

미달 시 이전 labels 유지.

---

## 4. Layer 2: Options Pricing — Heston + Fourier

### 4.1 Black-Scholes (Phase 1)

$$P = Ke^{-rT}N(-d_2) - SN(-d_1)$$

$$d_1 = \frac{\ln(S/K) + (r + \sigma^2/2)T}{\sigma\sqrt{T}}, \quad d_2 = d_1 - \sigma\sqrt{T}$$

**Greeks:**

$$\Delta_{\text{put}} = -N(-d_1), \quad \Gamma = \frac{N'(d_1)}{S\sigma\sqrt{T}}$$

$$\Theta_{\text{put}} = -\frac{SN'(d_1)\sigma}{2\sqrt{T}} + rKe^{-rT}N(-d_2), \quad \mathcal{V} = S\sqrt{T} \cdot N'(d_1)$$

**10-Delta Strike (Newton-Raphson):**

$$K^{(n+1)} = K^{(n)} - \frac{\Delta(K^{(n)}) + 0.10}{\Gamma(K^{(n)})}$$

Phase 1에서는 $\sigma = \text{VIX}/\sqrt{252} \cdot \sqrt{T}$로 근사.

### 4.2 Heston Model (Phase 2+)

$$dS_t = rS_t \, dt + \sqrt{v_t} S_t \, dW_t^{(1)}$$

$$dv_t = \kappa(\theta - v_t) \, dt + \sigma_v \sqrt{v_t} \, dW_t^{(2)}$$

$$\text{Corr}(dW^{(1)}, dW^{(2)}) = \rho$$

Parameters: $v_0$ (현재 variance), $\kappa$ (mean reversion), $\theta$ (long-run var), $\sigma_v$ (vol-of-vol), $\rho$ (correlation, 통상 < 0).

**Characteristic Function:**

$$\phi_T(\xi) = \exp\left\{i\xi(\ln S_0 + rT) + \frac{\kappa\theta}{\sigma_v^2}\left[(\kappa - \rho\sigma_v i\xi - d)T - 2\ln\frac{1 - ge^{-dT}}{1-g}\right] + \frac{v_0}{\sigma_v^2}(\kappa - \rho\sigma_v i\xi - d)\frac{1 - e^{-dT}}{1 - ge^{-dT}}\right\}$$

$$d = \sqrt{(\rho\sigma_v i\xi - \kappa)^2 + \sigma_v^2(i\xi + \xi^2)}, \quad g = \frac{\kappa - \rho\sigma_v i\xi - d}{\kappa - \rho\sigma_v i\xi + d}$$

### 4.3 Carr-Madan FFT Pricing

Damped call price: $\tilde{c}_T(k) = e^{\alpha k} c_T(k)$, $k = \ln K$

$$\tilde{C}_T(\xi) = \frac{e^{-rT} \phi_T(\xi - (\alpha+1)i)}{\alpha^2 + \alpha - \xi^2 + i(2\alpha+1)\xi}$$

**전체 strike 가격 — FFT 한 번:**

$$c_T(k_j) = \frac{e^{-\alpha k_j}}{\pi} \text{Re}\left[\text{FFT}^{-1}\left\{\tilde{C}_T(\xi_n) \cdot e^{i\xi_n b} \cdot \eta\right\}\right]$$

$O(N \log N)$으로 $N$개 strike 동시 계산.

### 4.4 Daily Calibration

$$\hat{\Theta} = \argmin_{(v_0,\kappa,\theta,\sigma_v,\rho)} \sum_{i,j} w_{ij}\left(V_{\text{model}}(K_i, T_j) - V_{\text{mkt}}(K_i, T_j)\right)^2$$

- $w_{ij}$: vega weighting
- Optimizer: Differential evolution (global) → Levenberg-Marquardt (local)
- 소요 시간: ~수 초 (FFT 효율성 덕분)

**Constraints:**

- Feller condition: $2\kappa\theta > \sigma_v^2$ 강제. 이 조건이 깨지면 variance process가 0에 닿을 수 있어 수치적으로 불안정해진다. DE optimizer의 bound constraint로 구현.
- Parameter bounds: $v_0 \in [0.001, 1.0]$, $\kappa \in [0.1, 10]$, $\theta \in [0.01, 1.0]$, $\sigma_v \in [0.1, 2.0]$, $\rho \in [-0.95, -0.1]$

**Calibration 실패 시 Fallback (3단계):**

1. LM refinement 실패 → DE 결과만 사용
2. DE 수렴 실패 (RMSE > market bid-ask spread) → 전일 calibrated 파라미터 사용, WARNING alert
3. 2일 연속 실패 → BS closed-form으로 퇴행, CRITICAL alert

**Timing:** 매일 시장 마감(16:00 ET) 이후 EOD options chain으로 calibration 실행. 다음 trading day의 entry decision에 사용. Intraday recalibration 없음.

### 4.5 Vol Surface Outputs

Calibration 후 생성:

- $\sigma(K, T)$: 모든 (strike, maturity)에서 implied vol
- $\Delta, \Gamma, \Theta, \mathcal{V}$: 거래 대상 spread의 Greeks
- Richness score: $R = V_{\text{mkt}} - V_{\text{model}}$

---

## 5. Layer 3: Strategy Engine

### 5.1 Put Credit Spread

Short OTM Put ($K_1$) + Long further OTM Put ($K_2 = K_1 - W$).

**Payoff:**

$$\text{P\&L}(S_T) = \begin{cases} \Pi & \text{if } S_T > K_1 \\ \Pi - (K_1 - S_T) & \text{if } K_2 < S_T \leq K_1 \\ \Pi - W & \text{if } S_T \leq K_2 \end{cases}$$

Max profit = $\Pi$ (net premium). Max loss = $W - \Pi$. Defined at entry.

### 5.2 Entry Decision

$$\text{Enter} = \mathbb{1}[\text{Regime OK}] \cdot \mathbb{1}[\text{VRP OK}] \cdot \mathbb{1}[\text{Premium OK}]$$

**Regime:**

| $P_{\text{HighVol}}$ | Action |
|----------------------|--------|
| < 0.2 | Full position |
| 0.2 - 0.5 | Half position |
| 0.5 - 0.8 | Skip |
| > 0.8 | Skip + 기존 포지션 조기 청산 고려 |

**VRP:** $z_{\text{VRP}} > -1.0$

**Premium:** $\Pi / W > 0.10$ (10% minimum)

### 5.3 Strike Selection

```
1. Target: 10-delta put (≈ 90% OTM expiry 확률)
2. DTE: 30-45일
3. Newton-Raphson으로 정확한 10-delta strike 계산
4. Round to nearest tradeable strike (SPX $5 increments)
5. K_2 = K_1 - W (W = $50 or $100)
```

### 5.4 Position Management

Close if:
- DTE ≤ 7 (gamma risk)
- P&L ≥ 75% × $\Pi$ (profit target)
- P&L ≤ -2 × $\Pi$ (stop loss)
- $P_{\text{HighVol}} > 0.8$ (regime emergency)

---

## 6. Layer 4: Risk Management

### 6.1 Stage 1 — Vol Scaling

$$f_{\text{vol}} = \text{clip}\left(\frac{\sigma_{\text{target}}}{\hat{\sigma}_p}, \; 0.3, \; 1.5\right)$$

$\sigma_{\text{target}} = 0.12$ (12%). $\hat{\sigma}_p$: 20일 portfolio realized vol.

### 6.2 Stage 2 — Kelly Ceiling

$$f_{\text{Kelly}} = \text{clip}\left(\frac{\hat{\mu}_p}{\hat{\sigma}_p^2}, \; 0.2, \; 2.0\right)$$

**Regime-conditional prior with adaptive weighting:**

$$\hat{\mu}_p = \alpha_t \cdot \mu_{\text{prior}}(\text{regime}_t) + (1 - \alpha_t) \cdot \hat{\mu}_{\text{rolling}}(60d)$$

$\alpha_t$는 regime 전환의 긴급성에 따라 조정된다:

$$\alpha_t = \begin{cases} 0.6 & \text{if regime unchanged for } \geq 5\text{d} \quad \text{(steady state)} \\ 0.9 & \text{if regime transitioned to High-Vol within } < 5\text{d} \quad \text{(emergency)} \\ 0.75 & \text{if regime transitioned (non-HV) within } < 5\text{d} \quad \text{(transition)} \end{cases}$$

근거: Regime이 갑자기 High-Vol로 전환될 때, 60일 rolling mean은 아직 최근의 좋은 성과를 반영하고 있어 blended estimate가 위험을 과소평가할 수 있다. High-Vol 전환 시 prior weight를 0.9로 올려 μ_prior=2%의 보수적 추정이 즉시 반영되도록 한다.

| Regime | $\mu_{\text{prior}}$ |
|--------|---------------------|
| Low-Vol | 15% |
| Normal-Vol | 8% |
| High-Vol | 2% |

### 6.3 Stage 3 — Drawdown Override

$$f_{\text{DD}} = \begin{cases} 1.0 & \text{DD} < 5\% \\ 0.5 & 5\% \leq \text{DD} < 10\% \\ 0.0 & \text{DD} \geq 10\% \end{cases}$$

### 6.4 min-Chain

$$f_{\text{final}} = \min(f_{\text{vol}}, \; f_{\text{Kelly}}, \; f_{\text{DD}})$$

세 stage 모두 독립적인 leverage 의견이며, 가장 보수적인 의견을 따른다. 곱셈은 사용하지 않는다 — 곱하면 이중/삼중 risk adjustment가 되어 불필요하게 보수적이 된다.

$f_{\text{DD}} = 0$일 때 $\min$은 0을 리턴하므로 kill switch 기능은 동일하다. $f_{\text{DD}} = 0.5$일 때가 이전 설계와 다르다: 예를 들어 $f_{\text{vol}} = 0.8$, $f_{\text{Kelly}} = 1.2$, $f_{\text{DD}} = 0.5$인 경우, $\min = 0.5$ (DD의 의견을 따른다). 이전 곱셈 방식에서는 $0.8 \times 0.5 = 0.4$로 DD와 vol이 중복 조정되었다.

---

## 7. Layer 5: Execution

### 7.1 Position Sizing

$$N_{\text{spreads}} = \left\lfloor \frac{\text{Account} \times f_{\text{final}}}{\text{Max Loss per Spread}} \right\rfloor$$

$$\text{Max Loss per Spread} = (W - \Pi) \times 100$$

### 7.2 Greeks Monitoring

$$\Delta_{\text{total}} = N \times \Delta_{\text{spread}} \times 100, \quad \mathcal{V}_{\text{total}} = N \times \mathcal{V}_{\text{spread}} \times 100$$

| Metric | Limit |
|--------|-------|
| $|\Delta_{\text{total}}|$ | < 5% of Account |
| $|\mathcal{V}_{\text{total}}|$ | < 2% of Account per 1% vol |

### 7.3 IBKR Execution

```
Entry:
  1. Regime + VRP + Premium check → GO/NO-GO
  2. 10-delta strike 계산 → nearest tradeable
  3. Limit order at mid-price
  4. 30s 미체결 → 1 tick aggressive
  5. 2min 미체결 → cancel

Exit:
  1. 75% profit → market close
  2. Stop loss → market close
  3. DTE ≤ 7 → close regardless
  4. Regime emergency → market close
```

### 7.4 Slippage Model & Stress Test

10-delta OTM put spread의 bid-ask은 regime에 따라 극적으로 변한다:

| Regime | 예상 bid-ask (per leg) | Slippage 가정 |
|--------|----------------------|--------------|
| Low-Vol | $0.10-0.30 | 25% of spread |
| Normal-Vol | $0.20-0.50 | 25% of spread |
| High-Vol (emergency exit) | $0.50-2.00+ | **50% of spread** |

Backtest의 기본 slippage 가정(25%)은 normal 환경 기준이다. **High-Vol emergency exit에서는 50% slippage를 적용한 stress backtest를 별도 실행한다.** 이 stress test에서도 전체 Sharpe > 0.3, MDD < 30%을 유지해야 한다.

추가로, position 크기가 해당 strike의 일평균 거래량의 1%를 초과하지 않도록 한다. SPX 옵션은 유동성이 높지만, deep OTM에서는 volume이 급감할 수 있다.

---

## 8. End-to-End Flow

```
t = today

Step 1: Data
  → S_t, VIX_t, VIX3M_t, VVIX_t
  → Compute RV(5,21,63), TS, ΔVol, z_VRP
  → Options chain (Phase 2+)

Step 2: Regime
  → p_t = [P_LV, P_NV, P_HV]

Step 3: Pricing
  → Phase 1: BS closed-form
  → Phase 2+: Heston calibrate → vol surface → Greeks

Step 4: Entry Decision
  → P_HV < threshold AND z_VRP > -1.0 AND Π/W > 10%
  → If pass → Step 5. If fail → skip.

Step 5: Risk Sizing
  → f_final = min(f_vol, f_Kelly) × f_DD
  → N_spreads = floor(Account × f_final / MaxLoss)

Step 6: Execute via IBKR

Step 7: Daily Monitor
  → Greeks update, DD check, exit triggers
```

---

## 9. Backtest Framework

### 9.1 Phase 1: VIX Proxy Backtest

**Data:** VIX, VIX3M, SPX OHLCV, VVIX (2004-2025, ~20 years). 무료.

**Proxy P&L:**

$$r_{\text{proxy},t} = \frac{1}{\tau}\left(\frac{\text{VIX}_{t-\tau}^2}{252} - \frac{\text{RV}_t(\tau)^2}{252}\right) \times f_{\text{final},t-\tau}$$

**GO/NO-GO:**

| Metric | GO | NO-GO |
|--------|-----|-------|
| Regime-conditioned Sharpe | > 0.4 | ≤ 0.4 |
| MDD | < 30% | ≥ 30% |
| Naive vs Regime Sharpe diff | > 0.1 | ≤ 0.1 |
| 2008 drawdown | < 25% | ≥ 25% |
| 2020 March drawdown | < 20% | ≥ 20% |
| Positive VRP months | > 70% | ≤ 70% |
| CVaR(95%) monthly | > -8% | ≤ -8% |
| Worst single month | > -15% | ≤ -15% |

CVaR(95%)과 worst month를 추가한 이유: short vol 전략은 수익 분포가 fat-tailed이다 (대부분 소폭 이익, 가끔 대폭 손실). Sharpe과 MDD만으로는 좌측 꼬리의 심각도를 충분히 포착하지 못한다.

### 9.2 Phase 2: Options Chain Backtest

**Data:** Polygon.io ($29/mo) SPX options snapshots.

**Method:** 매주 실제 10-delta put spread 구성, 정확한 P&L:

$$\text{P\&L}_i = \Pi_i - \max(0, K_{1,i} - S_{T_i}) + \max(0, K_{2,i} - S_{T_i})$$

Costs: $0.65/contract + bid-ask 25% slippage.

**GO/NO-GO:**

| Metric | GO |
|--------|-----|
| Post-cost Sharpe | > 0.5 |
| MDD | < 25% |
| Win rate | > 75% |
| Avg win / Avg loss | > 0.3 |
| Phase 1 vs 2 correlation | > 0.7 |
| CVaR(95%) monthly | > -6% |
| Worst single month | > -12% |
| Stress slippage (50%) Sharpe | > 0.3 |

### 9.3 Overfitting Defense

- CPCV: $N=5$, $k=2$ → 10 splits, 5-day embargo
- PBO < 5%
- Parameter sensitivity: ±20% 변동 → Sharpe ±30% 이내

---

## 10. Parameter Reference

| Parameter | Value | Layer | Tunable |
|-----------|-------|-------|---------|
| **VRP** | | | |
| RV window | 21d | L0 | No |
| z-score window | 252d | L0 | No |
| z-score entry min | -1.0 | L0 | [-2, 0] |
| **Regime** | | | |
| HMM states | 3 | L1 | No |
| HMM features | 5 | L1 | No |
| HMM min window | 504d | L1 | No |
| n_init | 10 | L1 | No |
| Label stability | ≥ 90% | L1 | No |
| XGB estimators/depth | 200/4 | L1 | No |
| Brier score | < 0.25 | L1 | No |
| **Pricing** | | | |
| Phase 1 | BS closed-form | L2 | No |
| Phase 2+ | Heston + FFT | L2 | No |
| FFT grid | 4096 | L2 | No |
| Damping α | 1.5 | L2 | No |
| Calibration | DE → LM | L2 | No |
| **Strategy** | | | |
| Underlying | SPX | L3 | No |
| Type | Put credit spread | L3 | No |
| DTE | 30-45d | L3 | No |
| Short delta | 10-delta | L3 | [5, 16] |
| Spread width | $50-100 | L3 | [$25, $150] |
| Frequency | Weekly | L3 | No |
| Profit target | 75% | L3 | [50%, 90%] |
| Stop loss | 2× premium | L3 | [1.5×, 3×] |
| Close DTE | ≤ 7d | L3 | No |
| Min Π/W | 10% | L3 | [5%, 15%] |
| P_HV full | < 0.2 | L3 | No |
| P_HV half | 0.2-0.5 | L3 | No |
| P_HV skip | > 0.5 | L3 | No |
| P_HV emergency | > 0.8 | L3 | No |
| **Risk** | | | |
| σ_target | 12% | L4 | No |
| Vol max/min | 1.5/0.3 | L4 | No |
| Kelly α (steady) | 0.6 | L4 | [0.4, 0.8] |
| Kelly α (HV transition) | 0.9 | L4 | No |
| Kelly α (other transition) | 0.75 | L4 | No |
| Transition window | 5d | L4 | No |
| Kelly μ (LV/NV/HV) | 15/8/2% | L4 | [5%, 20%] |
| Kelly clip | [0.2, 2.0] | L4 | No |
| Kelly window | 60d | L4 | No |
| DD warn/reduce/kill | 5/5/10% | L4 | No |
| **Pricing (Practical)** | | | |
| Feller condition | Enforced | L2 | No |
| Calibration fallback | Prev day → BS | L2 | No |
| Calibration timing | EOD (16:00 ET) | L2 | No |
| **Execution** | | | |
| Normal slippage | 25% of bid-ask | L5 | No |
| Stress slippage (HV exit) | 50% of bid-ask | L5 | No |
| Max position / volume | < 1% daily vol | L5 | No |
| **Backtest** | | | |
| Phase 1 Sharpe | > 0.4 | BT | No |
| Phase 1 MDD | < 30% | BT | No |
| Phase 1 CVaR(95%) monthly | > -8% | BT | No |
| Phase 1 Worst month | > -15% | BT | No |
| Phase 2 Sharpe | > 0.5 | BT | No |
| Phase 2 MDD | < 25% | BT | No |
| Phase 2 Win rate | > 75% | BT | No |
| Phase 2 CVaR(95%) monthly | > -6% | BT | No |
| Phase 2 Stress slippage Sharpe | > 0.3 | BT | No |
| CPCV | N=5, k=2 | BT | No |
| PBO | < 5% | BT | No |

---

## Appendix: 두 시스템의 관계

```
┌─────────────────────────────────────────────────────────┐
│            VRP Production System (이 문서)               │
│                                                         │
│  Layer 0-1: VRP + Regime  ──┐                           │
│  Layer 2: Heston + Fourier ─┤──→ Trading decisions      │
│  Layer 3-5: Strategy/Risk   ─┘    → Real money          │
│                                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│       VRP Research System (mathematical_design.md)       │
│                                                         │
│  같은 Layer 0-1  ──────────────┐                        │
│  Path A: Heston + Fourier ─────┤                        │
│  Path B: PINN ─────────────────┤──→ Comparator          │
│  같은 Layer 3-5  ──────────────┘    → Research data     │
│                                     → 논문              │
│                                     → Path B 성숙 시    │
│                                       Production 개선   │
└─────────────────────────────────────────────────────────┘
```

Production은 Research의 결과를 기다리지 않는다. Research의 결론이 Production을 개선할 수 있으면 반영하고, 아니면 무시한다. 두 시스템은 독립적으로 운영된다.
