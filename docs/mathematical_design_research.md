# Mathematical Design — Variance Risk Premium Harvesting System

**Regime-Conditioned Systematic Short Volatility | SPX Options | Python**

> 이 문서는 VRP 시스템의 수학적 기초를 정의한다.
> 각 Layer의 수학적 모델, 입출력, 그리고 Layer 간 연결을 명시한다.
> Pipeline design, implementation blueprint, roadmap 문서의 수학적 근거 역할.

---

## Table of Contents

1. [System Overview — 수익의 수학적 원천](#1-system-overview)
2. [Layer 0: Variance Risk Premium — 정의와 측정](#2-layer-0-variance-risk-premium)
3. [Layer 1: Regime Detection — HMM + XGBoost](#3-layer-1-regime-detection)
4. [Layer 2: Dual-Path Options Pricing — Fourier + PINN + Comparator](#4-layer-2-dual-path-options-pricing-engine)
5. [Layer 3: Strategy Engine — Put Credit Spread Mechanics](#5-layer-3-strategy-engine)
6. [Layer 4: Risk Management — Vol Scaling, Kelly, DD Override](#6-layer-4-risk-management)
7. [Layer 5: Execution — Greeks와 Order Sizing](#7-layer-5-execution)
8. [End-to-End Mathematical Flow](#8-end-to-end-flow)
9. [Backtest Framework — 3-Phase Validation](#9-backtest-framework)
10. [Parameter Reference](#10-parameter-reference)

---

## 1. System Overview

### 1.1 수익의 수학적 원천

이 시스템의 기대수익은 세 개의 독립적 원천에서 발생한다:

$$E[R_{\text{total}}] = \underbrace{E[\text{VRP}]}_{\text{structural premium}} + \underbrace{E[\Delta R_{\text{regime}}]}_{\text{risk management alpha}} + \underbrace{E[\Delta R_{\text{selection}}]}_{\text{strike/timing alpha}}$$

**Term 1 — Structural VRP:** 옵션 시장의 구조적 비대칭에서 발생. 예측 불필요.

**Term 2 — Regime Conditioning:** Bear regime에서 exposure를 줄여 drawdown을 축소. 이는 기대수익을 높이는 것이 아니라 **geometric mean을 개선**하는 것이다:

$$G = \prod_{t=1}^{T}(1 + r_t)^{1/T} \approx \bar{r} - \frac{\sigma^2}{2}$$

Drawdown을 줄이면 $\sigma^2$ term이 감소하여, 산술 평균이 같더라도 복리 수익이 개선된다.

**Term 3 — Strike/Timing Selection:** Premium이 역사적 평균 대비 rich한 시점과 strike를 선별. Dual pricing engine의 비교 분석을 통해 정밀도를 높인다.

### 1.2 Architecture — Dual-Path Pricing

이 시스템의 핵심 설계 결정: Options pricing layer에 **두 개의 독립적 경로**를 두고, Comparator가 이 둘을 실시간으로 비교 평가한다.

- **Path A (Fourier):** Heston model + Carr-Madan FFT. Industry standard. Production trading의 primary engine.
- **Path B (PINN):** Physics-Informed Neural Network. Model-free. Research engine이자 Path A의 independent validation.

두 경로는 같은 시장 데이터를 입력받아 독립적으로 vol surface, Greeks, theoretical price를 생성한다. Comparator는 이 차이를 정량화하고, 어떤 영역(strike, DTE, regime)에서 차이가 크거나 작은지를 기록한다.

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
                    ┌──────────┴──────────┐
                    │   Market Data (t)   │
                    │  Options Chain + S_t │
                    └────┬───────────┬────┘
                         │           │
         ┌── Path A ─────┴──┐  ┌────┴───── Path B ──┐
         │  Heston Model     │  │  PINN Network      │
         │  Carr-Madan FFT   │  │  BS PDE Constraint │
         │  5-param calibr.  │  │  Model-free σ(S,t) │
         │                   │  │                    │
         │  → Vol Surface A  │  │  → Vol Surface B   │
         │  → Greeks A       │  │  → Greeks B        │
         │  → Prices A       │  │  → Prices B        │
         └────────┬──────────┘  └─────────┬──────────┘
                  │                       │
                  └───────┬───────────────┘
                          │
              ┌── Comparator ──────────────────────┐
              │  Surface Diff Map (A vs B)          │
              │  Greeks Diff (Δ, Γ, Θ, V per path) │
              │  Richness Score (mkt vs each path)  │
              │  Region Analysis (by strike/DTE)    │
              │  → Primary: Path A (trading)        │
              │  → Validation: Path B (research)    │
              └────────────┬───────────────────────┘
                           │
┌── Layer 3: Strategy ─────┴───────────────────────────────────┐
│  Regime probs → position size                                │
│  VRP level → entry/skip decision                             │
│  Primary pricing (Path A) → strike selection                 │
│  Comparator divergence → additional confidence signal        │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 4: Risk Management ──┴───────────────────────────────┐
│  Vol Scaling → Kelly Ceiling → DD Override                    │
│  min-chain (never multiplicative)                            │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌── Layer 5: Execution ────────┴───────────────────────────────┐
│  Greeks computation → order sizing → IBKR execution          │
└──────────────────────────────────────────────────────────────┘
```

**설계 원칙:** Path A는 항상 trading decision의 primary source이다. Path B는 Path A의 결과를 override하지 않는다. Comparator의 역할은 두 경로의 차이를 기록하고 분석하는 것이며, 이 분석 결과는 (1) Path B가 충분히 성숙했을 때 Path A를 대체하거나 보완하는 근거, (2) 학술 논문의 핵심 결과가 된다.

---

## 2. Layer 0: Variance Risk Premium — 정의와 측정

### 2.1 VRP의 수학적 정의

Variance Risk Premium은 risk-neutral variance와 physical variance의 차이다:

$$\text{VRP}_t = E^{\mathbb{Q}}_t[\sigma^2_{t,t+\tau}] - E^{\mathbb{P}}_t[\sigma^2_{t,t+\tau}]$$

여기서:
- $\mathbb{Q}$: risk-neutral measure (옵션 시장이 imply하는 세계)
- $\mathbb{P}$: physical measure (실제 세계)
- $\tau$: measurement horizon (통상 30일)

이 premium이 양수라는 것은 — 옵션 시장이 미래 변동성을 체계적으로 과대평가한다는 의미이다.

### 2.2 실현 변동성 (Realized Volatility)

$$\text{RV}_t(\tau) = \sqrt{\frac{252}{\tau} \sum_{i=1}^{\tau} r_{t-i}^2}$$

여기서 $r_t = \ln(S_t / S_{t-1})$은 S&P 500의 일별 로그 수익률.

**Parkinson (High-Low) 추정치** (효율성이 5배 높음):

$$\sigma_{\text{PK},t}^2 = \frac{1}{4\ln 2} \cdot \frac{252}{\tau} \sum_{i=1}^{\tau} \left(\ln \frac{H_{t-i}}{L_{t-i}}\right)^2$$

### 2.3 내재 변동성 (Implied Volatility)

VIX는 30일 expected variance의 model-free 추정치다:

$$\text{VIX}^2 = \frac{2}{\tau} \sum_i \frac{\Delta K_i}{K_i^2} e^{r\tau} \cdot Q(K_i) - \frac{1}{\tau}\left(\frac{F}{K_0} - 1\right)^2$$

여기서:
- $K_i$: OTM 옵션의 strike price
- $\Delta K_i = (K_{i+1} - K_{i-1}) / 2$
- $Q(K_i)$: 해당 strike의 mid price
- $F$: forward price, $K_0$: ATM 기준 strike

이 수식은 CBOE의 공식 VIX 계산 방법이다. Model-free이므로 Black-Scholes 가정에 의존하지 않는다.

### 2.4 VRP 측정 — Proxy vs Full

**Phase 1 Proxy (VIX 기반):**

$$\widehat{\text{VRP}}_t = \frac{\text{VIX}_t^2}{252} - \text{RV}_t(21)^2 / 252$$

일별 variance 단위. 양수이면 IV > RV (premium 존재).

**정규화된 VRP 신호:**

$$z_{\text{VRP},t} = \frac{\widehat{\text{VRP}}_t - \mu_{\text{VRP}}(252)}{\sigma_{\text{VRP}}(252)}$$

여기서 $\mu_{\text{VRP}}(252)$, $\sigma_{\text{VRP}}(252)$는 과거 252일의 rolling mean/std.

$z_{\text{VRP}} > 0$: premium이 역사적 평균 이상 → entry 유리
$z_{\text{VRP}} < -1$: premium이 이례적으로 낮음 → skip 고려

**Phase 2 Full (Options Chain 기반):**

실제 SPX 옵션 chain에서 직접 계산:

$$\text{IV}_{\text{spread}}(K_1, K_2, T) = \sigma_{\text{impl}}(K_1, T) - \text{RV}_t(\tau)$$

여기서 $K_1$(short leg), $K_2$(long leg)는 실제 거래할 put spread의 strike.

### 2.5 VIX Term Structure

$$\text{TS}_t = \frac{\text{VIX3M}_t}{\text{VIX}_t} - 1$$

- $\text{TS}_t > 0$ (Contango): 정상 상태. 시장이 calm. Short vol에 유리.
- $\text{TS}_t < 0$ (Backwardation): 공포 상태. 단기 vol이 장기보다 높음. 주의 필요.

이 지표는 Regime detection의 보조 feature이자, entry filter로 사용.

---

## 3. Layer 1: Regime Detection

### 3.1 목적

Regime detection의 목적은 **시장 방향 예측이 아니다.** 변동성 환경(vol regime)을 분류하여, short vol position의 크기를 조절하는 것이다.

### 3.2 Phase A — Gaussian Hidden Markov Model (Labeling)

시장을 3개의 latent state로 모델링한다: $S = \{\text{Low-Vol}, \text{Normal-Vol}, \text{High-Vol}\}$

기존 equity 설계의 Bull/Neutral/Bear와 다른 점: 여기서는 **수익률 방향이 아니라 변동성 수준**으로 state를 정의한다. Short vol 전략에서 중요한 것은 "시장이 오르냐 내리냐"가 아니라 "변동성이 폭발하느냐 안 하느냐"이기 때문이다.

**Observed feature vector:**

$$\mathbf{x}_t = \begin{bmatrix} \sigma_{\text{RV},t}(21) \\ \text{VIX}_t \\ \text{TS}_t \\ \text{VVIX}_t \\ \Delta\text{Vol}_t(5) \end{bmatrix}$$

여기서:
- $\sigma_{\text{RV},t}(21)$: 21일 realized volatility (annualized)
- $\text{VIX}_t$: CBOE Volatility Index
- $\text{TS}_t$: VIX term structure (VIX3M/VIX - 1)
- $\text{VVIX}_t$: Vol-of-vol (VIX의 변동성)
- $\Delta\text{Vol}_t(5) = (\sigma_{\text{RV},t}(5) - \sigma_{\text{RV},t}(21)) / \sigma_{\text{RV},t}(21)$: 단기 vol 가속도

**기존 equity 설계에서 변경된 점:** 일별 수익률 $r_t$과 volume change를 제거하고, VVIX와 vol 가속도를 추가. 이유: 수익률 방향보다 **vol dynamics** (vol이 상승 추세인지, vol의 vol이 높은지)가 short vol 포지션의 위험을 더 잘 설명한다.

**HMM Parameters** $\theta = \{\boldsymbol{\pi}, \mathbf{A}, \boldsymbol{\mu}_k, \boldsymbol{\Sigma}_k\}$:

$$\pi_k = P(s_1 = k) \qquad \text{(initial distribution)}$$

$$A_{jk} = P(s_t = k \mid s_{t-1} = j) \qquad \text{(transition matrix)}$$

$$\mathbf{x}_t \mid s_t = k \sim \mathcal{N}(\boldsymbol{\mu}_k, \boldsymbol{\Sigma}_k) \qquad \text{where } \boldsymbol{\mu}_k \in \mathbb{R}^5, \boldsymbol{\Sigma}_k \in \mathbb{R}^{5 \times 5} \text{ (full)}$$

**Parameter Estimation** via Baum-Welch (EM):

*E-step (Forward-Backward):*

$$\alpha_t(k) = \left[\sum_j \alpha_{t-1}(j) \cdot A_{jk}\right] \cdot \mathcal{N}(\mathbf{x}_t \mid \boldsymbol{\mu}_k, \boldsymbol{\Sigma}_k)$$

$$\beta_t(k) = \sum_j A_{kj} \cdot \mathcal{N}(\mathbf{x}_{t+1} \mid \boldsymbol{\mu}_j, \boldsymbol{\Sigma}_j) \cdot \beta_{t+1}(j)$$

$$\gamma_t(k) = P(s_t = k \mid \mathbf{x}_{1:T}) = \frac{\alpha_t(k) \cdot \beta_t(k)}{\sum_{k'} \alpha_t(k') \cdot \beta_t(k')}$$

*M-step:*

$$\hat{\boldsymbol{\mu}}_k = \frac{\sum_t \gamma_t(k) \cdot \mathbf{x}_t}{\sum_t \gamma_t(k)}$$

$$\hat{\boldsymbol{\Sigma}}_k = \frac{\sum_t \gamma_t(k) \cdot (\mathbf{x}_t - \hat{\boldsymbol{\mu}}_k)(\mathbf{x}_t - \hat{\boldsymbol{\mu}}_k)^\top}{\sum_t \gamma_t(k)}$$

**Training Protocol:**

- Expanding window (최소 504일), never rolling
- $n_{\text{init}} = 10$ random restarts, 최고 log-likelihood 선택
- Convergence: $n_{\text{iter}} = 200$, full covariance

**⚠️ Filtering only:** 실시간에서는 filtering probabilities $P(s_t = k \mid \mathbf{x}_{1:t})$만 사용. Smoothed probabilities $P(s_t = k \mid \mathbf{x}_{1:T})$는 미래 정보를 포함하므로 백테스트에서도 사용 금지.

### 3.3 Centroid-Anchored State Labeling

HMM은 state에 의미를 부여하지 않는다 (permutation invariance). Refit 시마다 state 0,1,2의 의미가 바뀔 수 있다. 이를 해결하기 위해 (mean-vol, mean-VIX) 2D centroid matching을 사용:

$$\text{centroid}_k = \left(\hat{\mu}_{k,\text{RV}}, \hat{\mu}_{k,\text{VIX}}\right)$$

**Reference centroids (초기 fit에서 설정):**

| State | RV | VIX | 특성 |
|-------|------|------|------|
| Low-Vol | < 12% | < 15 | 안정적, full premium 수확 |
| Normal-Vol | 12-20% | 15-25 | 정상, 기본 포지션 |
| High-Vol | > 20% | > 25 | 위험, 포지션 축소/중단 |

Refit 후 새로운 state를 nearest centroid에 할당:

$$\text{label}(k) = \argmin_{c \in \{\text{L,N,H}\}} \| \text{centroid}_k - \text{ref}_c \|_2$$

### 3.4 Phase B — XGBoost Real-time Classifier

HMM labels를 target으로 XGBoost를 학습. 왜 2단계인가: HMM의 Baum-Welch는 전체 시계열이 필요하므로 실시간 추론이 어렵다. XGBoost는 현재 시점의 feature만으로 예측 가능.

**Feature Set (HMM과 동일 + 추가):**

$$\mathbf{f}_t = \begin{bmatrix} \sigma_{\text{RV}}(5d, 21d, 63d) \\ \text{VIX}_t, \text{VIX3M}_t, \text{TS}_t \\ \text{VVIX}_t \\ \text{Put/Call Ratio}_t \\ \text{Credit Spread}_t \\ \text{Yield Curve Slope}_t \end{bmatrix}$$

**Calibrated Probability Output:**

Raw XGBoost outputs를 `CalibratedClassifierCV` (isotonic regression)로 보정:

$$\hat{\mathbf{p}}_t = \text{Calibrate}\left(\text{XGB}(\mathbf{f}_t)\right) = [P_{\text{LowVol}}, P_{\text{NormalVol}}, P_{\text{HighVol}}]$$

**Brier Score 검증:**

$$\text{BS} = \frac{1}{T} \sum_{t=1}^{T} \sum_{k=1}^{3} (p_{t,k} - o_{t,k})^2 < 0.25$$

여기서 $o_{t,k}$는 one-hot encoded actual label.

### 3.5 Label Stability Check

Refit 후 label agreement 검증:

$$\text{Agreement} = \frac{|\{t : \text{label}_{\text{new}}(t) = \text{label}_{\text{old}}(t)\}|}{|\text{overlap}|} \geq 0.90$$

미달 시 이전 labels 유지, XGBoost retraining 보류.

---

## 4. Layer 2: Dual-Path Options Pricing Engine

이 시스템에서 options pricing의 역할은 **거래 가격 결정이 아니다** (시장이 가격을 정해준다). 역할은:

1. Delta 계산 → strike selection (10-delta 기준)
2. Theoretical value 계산 → richness scoring
3. Greeks 계산 → risk measurement
4. **Path A vs Path B 비교 → model risk 정량화, 연구 데이터 축적**

### 4.0 공통 기초: Black-Scholes와 Heat Equation 변환

두 경로 모두 Black-Scholes PDE를 기반으로 한다. Phase 1(VIX proxy backtest)에서는 BS closed-form만으로 충분하며, Path A/B는 Phase 2 이후에 활성화된다.

**European Put 가격 (BS Closed-Form):**

$$P(S, K, T, r, \sigma) = Ke^{-rT}N(-d_2) - SN(-d_1)$$

$$d_1 = \frac{\ln(S/K) + (r + \sigma^2/2)T}{\sigma\sqrt{T}}, \quad d_2 = d_1 - \sigma\sqrt{T}$$

**Greeks:**

$$\Delta_{\text{put}} = -N(-d_1), \quad \Gamma = \frac{N'(d_1)}{S\sigma\sqrt{T}}$$

$$\Theta_{\text{put}} = -\frac{S N'(d_1) \sigma}{2\sqrt{T}} + rKe^{-rT}N(-d_2), \quad \mathcal{V} = S\sqrt{T} \cdot N'(d_1)$$

여기서 $N'(x) = \frac{1}{\sqrt{2\pi}} e^{-x^2/2}$ (standard normal PDF).

**10-Delta Strike 결정 (Newton-Raphson):**

$\Delta_{\text{put}} = -0.10$이 되는 strike $K^*$를 찾는다:

$$K^{(n+1)} = K^{(n)} - \frac{\Delta(K^{(n)}) - (-0.10)}{\Gamma(K^{(n)})}$$

Phase 1에서는 $\sigma = \text{VIX}/\sqrt{252}$로 근사. Phase 2 이후에는 각 Path에서 생성한 vol surface의 $\sigma_{\text{impl}}(K, T)$를 사용.

**Heat Equation 변환 (두 경로의 공통 수학적 기반):**

BS PDE:

$$\frac{\partial V}{\partial t} + \frac{1}{2}\sigma^2 S^2 \frac{\partial^2 V}{\partial S^2} + rS\frac{\partial V}{\partial S} - rV = 0$$

변수 변환: $x = \ln(S/K)$, $\tau = \frac{1}{2}\sigma^2(T - t)$, $V = K e^{-\alpha x - \beta \tau} u(x, \tau)$

$$\alpha = -\frac{1}{2}\left(\frac{2r}{\sigma^2} - 1\right), \quad \beta = -\frac{1}{4}\left(\frac{2r}{\sigma^2} + 1\right)^2$$

이 변환 하에서 BS PDE는 heat equation이 된다:

$$\frac{\partial u}{\partial \tau} = \frac{\partial^2 u}{\partial x^2}$$

이 변환은 두 가지 의의가 있다:
- **Path A (Fourier):** Fourier transform이 heat equation에서 자연스럽게 작동. PDE가 frequency domain에서 단순 ODE가 된다.
- **Path B (PINN):** 비선형 coefficient $S^2$가 사라져 neural network 학습이 수치적으로 안정적이 된다.

---

### 4.1 Path A: Fourier Pricing Engine (Production)

Path A는 parametric model (Heston)을 가정하고, Fourier transform으로 효율적으로 pricing한다. **Trading decision의 primary source.**

#### 4.1.1 Heston Stochastic Volatility Model

$$dS_t = rS_t \, dt + \sqrt{v_t} S_t \, dW_t^{(1)}$$

$$dv_t = \kappa(\theta - v_t) \, dt + \sigma_v \sqrt{v_t} \, dW_t^{(2)}$$

$$\text{Corr}(dW^{(1)}, dW^{(2)}) = \rho$$

Parameters:
- $v_0$: 현재 instantaneous variance
- $\kappa$: mean reversion speed of variance
- $\theta$: long-run variance level
- $\sigma_v$: vol-of-vol
- $\rho$: stock-vol correlation (통상 $\rho < 0$, leverage effect)

Heston을 선택한 이유: (1) Characteristic function이 closed-form이어서 FFT pricing이 가능, (2) 5개 파라미터로 vol smile의 주요 특성(skew, curvature)을 포착, (3) Vol dynamics (mean-reversion + stochastic)가 VRP 전략의 핵심 변수인 vol 자체를 모델링.

**Heston의 한계 (Path B가 필요한 이유):** Heston은 5개 파라미터로 entire vol surface를 fit한다. 실제 시장 surface는 Heston이 완벽히 표현 못하는 구조가 있다 — 특히 short-dated deep OTM put (Brian이 거래하는 정확히 그 영역)에서 skew를 underestimate하는 경향이 있다. 이 model misspecification이 실제 P&L에 얼마나 영향을 미치는지가 Comparator가 답해야 할 핵심 질문이다.

#### 4.1.2 Characteristic Function

$$\phi_T(\xi) = \exp\left\{i\xi(\ln S_0 + rT) + \frac{\kappa\theta}{\sigma_v^2}\left[(\kappa - \rho\sigma_v i\xi - d)T - 2\ln\frac{1 - ge^{-dT}}{1-g}\right] + \frac{v_0}{\sigma_v^2}(\kappa - \rho\sigma_v i\xi - d)\frac{1 - e^{-dT}}{1 - ge^{-dT}}\right\}$$

$$d = \sqrt{(\rho\sigma_v i\xi - \kappa)^2 + \sigma_v^2(i\xi + \xi^2)}, \quad g = \frac{\kappa - \rho\sigma_v i\xi - d}{\kappa - \rho\sigma_v i\xi + d}$$

**왜 characteristic function인가:** Heat equation에서 Fourier transform이 PDE를 ODE로 바꾸는 것과 동일한 원리. $\phi_T(\xi)$는 log-price의 risk-neutral distribution의 Fourier transform이다. Price domain에서 복잡한 적분이 Fourier domain에서 해석적으로 풀린다.

#### 4.1.3 Carr-Madan FFT Pricing

Modified call price에 damping factor $\alpha > 0$을 도입:

$$\tilde{c}_T(k) = e^{\alpha k} c_T(k), \quad k = \ln K$$

이것의 Fourier transform:

$$\tilde{C}_T(\xi) = \frac{e^{-rT} \phi_T(\xi - (\alpha+1)i)}{\alpha^2 + \alpha - \xi^2 + i(2\alpha + 1)\xi}$$

**전체 strike에 대한 가격을 FFT 한 번으로 계산:**

$$c_T(k_j) = \frac{e^{-\alpha k_j}}{\pi} \text{Re}\left[\text{FFT}^{-1}\left\{\tilde{C}_T(\xi_n) \cdot e^{i\xi_n b} \cdot \eta \right\}\right]$$

핵심: $O(N \log N)$으로 $N$개 strike의 가격을 동시에 계산. Calibration loop에서 수천 번 호출되므로 이 효율성이 결정적이다.

Put price는 Put-Call parity로 변환: $P = C - Se^{-qT} + Ke^{-rT}$

#### 4.1.4 Calibration

시장 옵션 가격 $\{V_{\text{mkt}}(K_i, T_j)\}$에 대해:

$$\hat{\Theta}_A = \argmin_{(v_0, \kappa, \theta, \sigma_v, \rho)} \sum_{i,j} w_{ij} \left(V_{\text{model}}(K_i, T_j; \Theta) - V_{\text{mkt}}(K_i, T_j)\right)^2$$

- $w_{ij}$: vega weighting (ATM 근처에 높은 가중치, OTM에 낮은 가중치)
- $V_{\text{model}}$: Carr-Madan FFT로 계산
- Optimizer: Differential evolution (global) → Levenberg-Marquardt (local refinement)

#### 4.1.5 Path A Outputs

Calibration 완료 후 Path A가 생성하는 것들:

- **Vol Surface A:** $\sigma_A(K, T)$ — 모든 (strike, maturity)에서의 implied vol
- **Greeks A:** $\Delta_A, \Gamma_A, \Theta_A, \mathcal{V}_A$ — 거래 대상 spread의 Greeks
- **Theoretical Price A:** $V_A(K_1, K_2, T)$ — spread의 이론 가격
- **Richness Score A:** $R_A = V_{\text{mkt}} - V_A$ — 시장 가격과 이론 가격의 차이
- **Calibration Error:** $\epsilon_A = \text{RMSE}(\text{model vs market across all strikes})$

---

### 4.2 Path B: PINN Pricing Engine (Research)

Path B는 model assumption 없이, BS PDE를 physics constraint로 사용하여 neural network이 vol surface를 직접 학습한다. **Path A의 independent validation이자 연구 엔진.**

#### 4.2.1 PINN Architecture

Neural network $\mathcal{N}_\theta$를 두 가지 용도로 사용:

**Network 1 — Option Price Network $V_\theta(S, t)$:**

입력 $(S, t, K, T)$ → 출력 $\hat{V}$ (option theoretical price)

**Network 2 — Local Volatility Network $\sigma_\theta(S, t)$:**

입력 $(S, t)$ → 출력 $\hat{\sigma}$ (local volatility)

두 network은 jointly trained. $V_\theta$는 $\sigma_\theta$를 통해 BS PDE를 만족해야 한다.

Architecture: Fully connected, 4-6 hidden layers, 64-128 neurons/layer, $\tanh$ activation (PDE의 2nd derivative 계산을 위해 smooth activation 필요).

#### 4.2.2 Loss Function Design

$$\mathcal{L}_{\text{total}} = \lambda_1 \mathcal{L}_{\text{data}} + \lambda_2 \mathcal{L}_{\text{PDE}} + \lambda_3 \mathcal{L}_{\text{arb}} + \lambda_4 \mathcal{L}_{\text{BC}}$$

**Term 1 — Market Data Fit:**

$$\mathcal{L}_{\text{data}} = \frac{1}{N_m} \sum_{i=1}^{N_m} \left| V_\theta(S_0, t_0; K_i, T_i) - V_{\text{mkt}}(K_i, T_i) \right|^2$$

시장에서 관찰된 옵션 가격에 fit. $N_m$: 시장에서 관찰되는 (strike, expiry) 쌍의 수.

**Term 2 — BS PDE Constraint (Physics):**

$$\mathcal{L}_{\text{PDE}} = \frac{1}{N_r} \sum_{i=1}^{N_r} \left| \frac{\partial V_\theta}{\partial t} + \frac{1}{2}\sigma_\theta(S_i, t_i)^2 S_i^2 \frac{\partial^2 V_\theta}{\partial S^2} + rS_i\frac{\partial V_\theta}{\partial S} - rV_\theta \right|^2$$

$(S_i, t_i)$는 $(S, t)$ domain에서 sampling한 collocation points. $N_r \gg N_m$ (시장 데이터보다 훨씬 많은 PDE 검증 포인트).

편미분은 automatic differentiation으로 정확히 계산 — 이것이 PINN의 핵심 기술적 요소.

**Heat equation domain에서의 동등한 형태:**

변환 후에는 PDE loss가 더 단순해진다:

$$\mathcal{L}_{\text{PDE}}^{\text{heat}} = \frac{1}{N_r} \sum_{i=1}^{N_r} \left| \frac{\partial u_\theta}{\partial \tau}(x_i, \tau_i) - \frac{\partial^2 u_\theta}{\partial x^2}(x_i, \tau_i) \right|^2$$

교수님의 Step 1 (1D heat with Gaussian IC)이 여기의 기초 검증 역할을 한다.

**Term 3 — Arbitrage-Free Constraint:**

$$\mathcal{L}_{\text{arb}} = \frac{1}{N_a} \sum_{i=1}^{N_a} \left[\text{ReLU}\left(-\frac{\partial^2 C_\theta}{\partial K^2}\right) + \text{ReLU}\left(-\frac{\partial P_\theta}{\partial T}\right)\right]$$

두 가지 no-arbitrage 조건을 강제:
- Butterfly: $\frac{\partial^2 C}{\partial K^2} \geq 0$ (call price는 strike에 대해 convex)
- Calendar: $\frac{\partial P}{\partial T} \leq 0$ (put price는 만기가 길수록 비싸지 않음... 이건 American의 경우. European은 조건이 다름 — 실제 구현 시 재검토 필요)

**Term 4 — Boundary Conditions:**

$$\mathcal{L}_{\text{BC}} = \frac{1}{N_b} \sum_{i=1}^{N_b} \left| V_\theta(0, t_i) - Ke^{-r(T-t_i)} \right|^2 + \left| V_\theta(S_{\max}, t_i) - 0 \right|^2$$

Put option boundary: $S \to 0$이면 $V \to Ke^{-rT}$, $S \to \infty$이면 $V \to 0$.

**Loss Weight Scheduling:**

$$\lambda_1 = 1.0, \quad \lambda_2 = \lambda_2^{(0)} \cdot (1 + \text{epoch}/\text{ramp})$$

PDE weight를 점진적으로 증가: 초기에는 data fit에 집중하고, 학습이 진행되면서 PDE 준수를 강화. 이것이 PINN training 안정성의 핵심이다.

#### 4.2.3 Training Protocol

1. **Data Preparation:** 매 trading day의 options chain에서 $(K_i, T_j, V_{\text{mkt},ij})$ 추출
2. **Collocation Points:** $(S, t)$ domain에서 Latin Hypercube Sampling으로 $N_r = 10{,}000$ points
3. **Training:** Adam optimizer, learning rate $10^{-3}$ → cosine annealing to $10^{-5}$, 10,000-50,000 epochs
4. **Inference:** 학습 완료 후 forward pass로 임의의 $(K, T)$에서 가격과 Greeks를 밀리초 단위로 계산

**Warm Starting:** 전날 학습된 weights를 initialization으로 사용. Vol surface는 하루 사이에 급변하지 않으므로, warm start가 수렴을 크게 가속한다 (50,000 → ~5,000 epochs).

#### 4.2.4 Path B Outputs

Path A와 동일한 형식의 outputs:

- **Vol Surface B:** $\sigma_B(K, T) = \sigma_\theta(S_0 \cdot e^{\ln(K/S_0)}, T)$ — model-free implied vol
- **Greeks B:** $\Delta_B, \Gamma_B, \Theta_B, \mathcal{V}_B$ — automatic differentiation으로 계산
- **Theoretical Price B:** $V_B(K_1, K_2, T)$
- **Richness Score B:** $R_B = V_{\text{mkt}} - V_B$
- **PDE Residual:** $\epsilon_{\text{PDE}} = \text{mean}|\mathcal{L}_{\text{PDE}}|$ — PINN이 PDE를 얼마나 잘 만족하는지

---

### 4.3 Comparator Framework

Comparator는 Path A와 Path B의 outputs을 체계적으로 비교하는 모듈이다. 목적은 세 가지: (1) Path B의 성숙도 평가, (2) Path A의 model risk 정량화, (3) 연구 데이터 축적.

#### 4.3.1 Surface Difference Map

$$D_\sigma(K, T) = \sigma_B(K, T) - \sigma_A(K, T)$$

이 difference map을 moneyness ($K/S$) × DTE 공간에서 시각화. 어떤 영역에서 두 모델이 가장 다른지를 보여준다.

**가설:** Heston은 deep OTM put에서 skew를 underestimate한다. 따라서:

$$E[D_\sigma(K, T)] > 0 \quad \text{for } K/S < 0.90, \; T < 45\text{d}$$

이 가설이 맞는지 틀리는지가 핵심 연구 결과가 된다.

#### 4.3.2 Greeks Comparison

각 Greek에 대해 Path A vs B 차이를 기록:

$$\Delta_{\text{diff}} = |\Delta_A - \Delta_B|, \quad \Gamma_{\text{diff}} = |\Gamma_A - \Gamma_B|$$

**의의:** Greeks 차이가 크다는 것은 → 두 모델이 risk를 다르게 평가한다는 것 → strike selection이나 position sizing에 영향을 줄 수 있다.

#### 4.3.3 Richness Score Comparison

두 경로가 각각 "이 옵션이 rich한가/cheap한가"를 다르게 판단하는 경우:

$$\Delta R = R_A - R_B = (V_{\text{mkt}} - V_A) - (V_{\text{mkt}} - V_B) = V_B - V_A$$

$\Delta R > 0$이면: Path A가 시장 대비 cheaper하다고 판단 (= 더 rich하다고 봄)
$\Delta R < 0$이면: Path B가 시장 대비 cheaper하다고 판단

이 차이가 systematically 한 방향이면, 한 모델이 체계적으로 mispricing하고 있다는 증거.

#### 4.3.4 Backtest-Level Comparison (핵심)

같은 기간의 백테스트를 두 경로로 각각 돌린다:

- **Backtest A:** Path A의 vol surface로 strike selection → 실제 P&L 계산
- **Backtest B:** Path B의 vol surface로 strike selection → 실제 P&L 계산

비교 metrics:

$$\Delta\text{Sharpe} = \text{Sharpe}_B - \text{Sharpe}_A$$

$$\Delta\text{MDD} = \text{MDD}_B - \text{MDD}_A$$

$$\text{Strike Agreement} = \frac{|\{t : K_{1,A}(t) = K_{1,B}(t)\}|}{T}$$

**Strike Agreement가 높으면 (>90%):** 두 모델이 비슷한 strike를 선택한다 → Path B가 실용적 차이를 만들지 않음. 연구적으로는 "PINN이 Heston과 같은 결론에 도달"이라는 결과.

**Strike Agreement가 낮으면 (<80%):** 두 모델이 다른 strike를 선택한다 → P&L 차이 분석이 의미 있음. $\Delta\text{Sharpe} > 0$이면 PINN이 실질적으로 나은 pricing을 제공한다는 증거.

#### 4.3.5 Regime-Conditional Analysis

Comparator의 차이를 regime별로 분해:

$$D_\sigma^{(k)}(K, T) = E\left[D_\sigma(K, T) \;\big|\; \text{Regime} = k\right], \quad k \in \{\text{LV, NV, HV}\}$$

**가설:** High-Vol regime에서 Heston의 한계가 더 드러날 가능성이 높다 (극단적 skew, jumps 등). 따라서:

$$\|D_\sigma^{(\text{HV})}\| > \|D_\sigma^{(\text{LV})}\|$$

이것이 확인되면 — "High-Vol regime에서만 PINN pricing을 사용하고, Low/Normal에서는 Heston을 유지"하는 **hybrid switching** 전략의 근거가 된다.

---

### 4.4 Phase별 활성화

| Phase | Path A (Fourier) | Path B (PINN) | Comparator |
|-------|-----------------|---------------|------------|
| Phase 1 (VIX proxy) | BS closed-form only | 비활성 | 비활성 |
| Phase 2 (Options chain) | Heston + FFT 활성 | 비활성 | 비활성 |
| Phase 3 (Dual-path) | Production primary | 학습 + 추론 시작 | 활성, 데이터 축적 |
| Phase 4 (Evaluation) | 유지 | 성숙도 평가 | 통계적 유의성 검증 |
| Phase 5+ (Potential) | 유지 or 교체 | Primary 승격 가능 | 전환 기준 판단 |

**Phase 5 전환 기준 (Path B → Primary):**

Path B가 Path A를 대체하려면 다음을 모두 만족:

1. $\Delta\text{Sharpe} > 0.05$ (통계적으로 유의미한 P&L 개선)
2. PDE residual $< 10^{-4}$ (물리적 consistency)
3. 6개월 이상 연속 데이터에서 검증
4. High-Vol regime에서 $\|D_\sigma^{(\text{HV})}\|$의 방향이 일관적

이 기준을 만족하지 않으면 — Path B는 영구적으로 research/validation 역할로 남는다. 그것만으로도 가치가 있다 (Path A의 model risk를 정량화하는 것 자체가 연구 기여).

---

### 4.5 2D Extension (Future — 교수님 연구 경로)

교수님의 "move on to 2D/3D" 방향은 다자산 옵션에서의 PINN 적용이다.

**2D Heat Equation:**

$$\frac{\partial u}{\partial \tau} = \frac{\partial^2 u}{\partial x_1^2} + 2\rho_{12}\frac{\partial^2 u}{\partial x_1 \partial x_2} + \frac{\partial^2 u}{\partial x_2^2}$$

여기서 $\rho_{12}$는 두 자산의 상관관계.

**VRP 시스템에서의 2D 응용:**

- $x_1 = \ln(S_{\text{SPX}})$, $x_2 = \ln(\text{VIX})$ → SPX-VIX joint dynamics
- Dispersion trade: SPX vol vs individual stock vols
- Correlation trade: sector ETF 간 상관관계 변화에 대한 옵션 전략

**왜 PINN이 2D에서 강점을 갖는가:**

Fourier method는 2D에서도 가능하지만, 2D FFT의 grid가 $N^2$으로 커진다. 3D에서는 $N^3$ → curse of dimensionality. FDM도 마찬가지.

PINN은 mesh-free이므로 차원이 올라가도 collocation point 수가 선형적으로만 증가. 이것이 교수님이 "2D/3D로 가라"고 한 핵심 이유이다.

단, 이 확장은 현재 VRP 시스템의 scope 밖이다. 1D 시스템이 안정적으로 운영된 후에 별도 연구 프로젝트로 진행.

---

## 5. Layer 3: Strategy Engine — Put Credit Spread

### 5.1 Strategy Definition

**Put Credit Spread** = Short OTM Put + Long further OTM Put

구체적으로, 매주 (또는 regime에 따라):

1. 30-45 DTE expiry 선택
2. 10-delta put을 short: strike $K_1$
3. $K_1$보다 $W$ 아래 put을 long: strike $K_2 = K_1 - W$

**Payoff at Expiration:**

$$\text{P\&L}(S_T) = \begin{cases}
\text{Premium received} & \text{if } S_T > K_1 \\
\text{Premium} - (K_1 - S_T) & \text{if } K_2 < S_T \leq K_1 \\
\text{Premium} - W & \text{if } S_T \leq K_2
\end{cases}$$

**Maximum profit** = Net premium received

**Maximum loss** = $W - \text{Premium}$

**Breakeven** = $K_1 - \text{Premium}$

### 5.2 Premium Calculation

Net premium received:

$$\Pi = P(K_1, T, \sigma_1) - P(K_2, T, \sigma_2)$$

여기서 $\sigma_1, \sigma_2$는 각 strike의 implied volatility.

**Spread의 Greeks:**

$$\Delta_{\text{spread}} = \Delta(K_1) - \Delta(K_2)$$

$$\Gamma_{\text{spread}} = \Gamma(K_1) - \Gamma(K_2)$$

$$\Theta_{\text{spread}} = \Theta(K_1) - \Theta(K_2)$$

$$\mathcal{V}_{\text{spread}} = \mathcal{V}(K_1) - \mathcal{V}(K_2)$$

Short spread이므로 $\Theta_{\text{spread}} > 0$ (시간 경과에 따라 수익), $\mathcal{V}_{\text{spread}} < 0$ (vol 상승 시 손실).

### 5.3 Entry Decision Logic

매주 entry 결정은 세 가지 조건의 AND:

$$\text{Enter} = \mathbb{1}[\text{Regime OK}] \cdot \mathbb{1}[\text{VRP OK}] \cdot \mathbb{1}[\text{Premium OK}]$$

**Condition 1 — Regime:**

$$\text{Regime OK} \iff P_{\text{HighVol},t} < \tau_{\text{regime}}$$

Regime probability vector에서 High-Vol 확률이 threshold 이하.

$\tau_{\text{regime}}$는 regime별로 다른 action과 연동:

| $P_{\text{HighVol}}$ | Action |
|----------------------|--------|
| $< 0.2$ | Full position |
| $0.2 - 0.5$ | Half position |
| $0.5 - 0.8$ | Skip (no new entry) |
| $> 0.8$ | Skip + 기존 포지션 조기 청산 고려 |

**Condition 2 — VRP Level:**

$$\text{VRP OK} \iff z_{\text{VRP},t} > z_{\text{min}}$$

Premium이 역사적으로 너무 낮지 않은지 확인. $z_{\text{min}} = -1.0$ (default).

**Condition 3 — Minimum Premium:**

$$\text{Premium OK} \iff \frac{\Pi}{W} > R_{\text{min}}$$

Received premium / max loss ratio가 최소 기준 이상. $R_{\text{min}} = 0.10$ (10%).

### 5.4 Strike Selection Algorithm

```
Input:  S_t (current SPX), σ_ATM, T (target DTE), r, W (spread width)
Output: K_1 (short strike), K_2 (long strike)

1. Initial guess: K_1^(0) = S_t * exp(-σ_ATM * sqrt(T) * N^{-1}(0.90))
2. Newton-Raphson iteration:
   a. Compute σ_impl(K_1^(n)) from vol surface (or smile interpolation)
   b. Compute Δ(K_1^(n)) using BS with σ_impl(K_1^(n))
   c. K_1^(n+1) = K_1^(n) - (Δ(K_1^(n)) + 0.10) / Γ(K_1^(n))
   d. Repeat until |Δ(K_1^(n)) + 0.10| < 0.001
3. Round K_1 to nearest tradeable strike (SPX: $5 increments)
4. K_2 = K_1 - W (W = $50 or $100)
```

### 5.5 Position Management

**Roll/Close Rules:**

$$\text{Close if:} \begin{cases}
\text{DTE} \leq 7 & \text{(gamma risk avoidance)} \\
\text{P\&L} \geq 0.75 \cdot \Pi & \text{(75\% profit target)} \\
\text{P\&L} \leq -(2 \cdot \Pi) & \text{(stop loss)} \\
P_{\text{HighVol}} > 0.8 & \text{(regime emergency)}
\end{cases}$$

75% profit target의 근거: 마지막 25% premium을 수확하는 데 남은 gamma risk가 불비례하게 크다.

---

## 6. Layer 4: Risk Management

기존 equity 설계의 min-chain 구조를 그대로 유지하되, short vol에 맞게 파라미터를 조정한다.

### 6.1 Stage 1 — Volatility Scaling (Daily Driver)

**목적:** 포트폴리오의 실현 변동성을 목표 수준에 맞춘다.

$$f_{\text{vol},t} = \frac{\sigma_{\text{target}}}{\hat{\sigma}_{p,t}}$$

$$\hat{\sigma}_{p,t} = \sqrt{\frac{252}{20} \sum_{i=1}^{20} r_{p,t-i}^2}$$

$$f_{\text{vol},t} = \text{clip}(f_{\text{vol},t}, \; f_{\text{vol,min}}, \; f_{\text{vol,max}})$$

Parameters:
- $\sigma_{\text{target}} = 0.12$ (12% annualized — equity 설계의 15%보다 낮음. Short vol은 본질적으로 fat-tail risk가 있으므로)
- $f_{\text{vol,max}} = 1.5$
- $f_{\text{vol,min}} = 0.3$

### 6.2 Stage 2 — Kelly Ceiling (Edge-Based Cap)

**Portfolio-level Kelly with Regime-Conditional Prior:**

Short vol의 expected return과 variance를 추정하여 optimal fraction을 계산:

$$f_{\text{Kelly}} = \frac{\hat{\mu}_p}{\hat{\sigma}_p^2}$$

**Regime-conditional prior $\mu_{\text{prior}}$:**

| Regime | $\mu_{\text{prior}}$ | 근거 |
|--------|---------------------|------|
| Low-Vol | 0.15 (15%) | VRP 가장 안정적, premium 꾸준 |
| Normal-Vol | 0.08 (8%) | 표준적 VRP 수확 |
| High-Vol | 0.02 (2%) | Premium 크지만 실현 risk도 극대 |

**Shrinkage (Bayesian combination):**

$$\hat{\mu}_p = \alpha \cdot \mu_{\text{prior}}(\text{regime}) + (1 - \alpha) \cdot \hat{\mu}_{\text{rolling}}(60d)$$

$\alpha = 0.6$ (prior에 더 많은 weight — short vol의 rolling return은 잡음이 크다).

**Final Kelly factor:**

$$f_{\text{Kelly}} = \text{clip}\left(\frac{\hat{\mu}_p}{\hat{\sigma}_p^2}, \; 0.2, \; 2.0\right)$$

### 6.3 Stage 3 — Drawdown Override (Emergency Brake)

$$f_{\text{DD},t} = \begin{cases}
1.0 & \text{if DD}_t < 5\% \quad \text{(normal)} \\
0.5 & \text{if } 5\% \leq \text{DD}_t < 10\% \quad \text{(warn → reduce)} \\
0.0 & \text{if DD}_t \geq 10\% \quad \text{(kill → full exit)}
\end{cases}$$

DD thresholds가 equity 설계(5/10/15%)보다 타이트하다 (5/10%). 이유: short vol의 손실은 convex하게 확대되므로, 더 빨리 빠져야 한다.

### 6.4 min-Chain Combination

$$f_{\text{final},t} = \min\left(f_{\text{vol},t}, \; f_{\text{Kelly},t}\right) \cdot \mathbb{1}[f_{\text{DD},t} > 0] \cdot f_{\text{DD},t}$$

**왜 min인가 (곱하기가 아닌 이유):**

각 stage는 독립적인 leverage 의견이다:
- Vol scaling: "변동성 기준으로 이만큼이 적절"
- Kelly: "edge 기준으로 이만큼이 최대"
- DD override: "비상 상황에서는 이만큼으로 제한"

이들을 곱하면 triple risk adjustment가 되어 시스템이 과도하게 보수적이 된다. min을 취하면 **가장 보수적인 의견을 따르되, 이중 조정은 피한다**.

DD override는 0/1이 아닌 연속 값을 사용하여 cliff effect를 방지한다.

---

## 7. Layer 5: Execution

### 7.1 Position Sizing

전체 계좌 대비 spread 수 결정:

$$N_{\text{spreads}} = \left\lfloor \frac{\text{Account} \times f_{\text{final},t}}{\text{Max Loss per Spread}} \right\rfloor$$

$$\text{Max Loss per Spread} = (W - \Pi) \times 100$$

($\times 100$은 SPX 옵션의 multiplier)

예시: Account = $100K, $f_{\text{final}} = 0.8$, $W = \$50$, $\Pi = \$7$
→ Max Loss = ($50 - $7) × 100 = $4,300
→ $N = \lfloor 80{,}000 / 4{,}300 \rfloor = 18$ spreads

### 7.2 Greeks-Based Risk Monitoring

포지션 전체의 aggregate Greeks:

$$\Delta_{\text{total}} = N \times \Delta_{\text{spread}} \times 100$$

$$\Gamma_{\text{total}} = N \times \Gamma_{\text{spread}} \times 100$$

$$\Theta_{\text{total}} = N \times \Theta_{\text{spread}} \times 100$$

$$\mathcal{V}_{\text{total}} = N \times \mathcal{V}_{\text{spread}} \times 100$$

**Risk Limits:**

| Metric | Limit | Action |
|--------|-------|--------|
| $|\Delta_{\text{total}}|$ | < 0.05 × Account | Delta가 커지면 market direction risk |
| $|\mathcal{V}_{\text{total}}|$ | < 0.02 × Account per 1% vol move | Vol spike 시 손실 제한 |
| $\Gamma_{\text{total}}$ | Monitor, no hard limit | DTE < 14에서 급증 시 주의 |

### 7.3 Execution via IBKR

```
Entry:
  1. Regime check → position size 결정
  2. 10-delta strike 계산 → nearest tradeable strike
  3. Limit order: mid-price에 진입 (market order 금지)
  4. 30초 미체결 시 → 1 tick aggressive
  5. 2분 미체결 시 → cancel, 다음 기회 대기

Exit:
  1. 75% profit → close at market (빠른 청산 우선)
  2. Stop loss → close at market
  3. DTE ≤ 7 → close regardless of P&L
  4. Regime emergency → close at market
```

---

## 8. End-to-End Mathematical Flow

일별 실행 흐름 (Phase 3 이후, dual-path 활성 상태):

```
t = today

Step 1: Data Update
  → S_t, VIX_t, VIX3M_t, VVIX_t, option chain
  → Compute RV_t(5,21,63), TS_t, ΔVol_t, z_VRP_t

Step 2: Regime Detection
  → x_t = [RV_21, VIX, TS, VVIX, ΔVol]
  → p_t = XGBoost_calibrated(f_t) = [P_LV, P_NV, P_HV]

Step 3: Dual-Path Pricing (parallel)
  → Path A: Heston calibration → Carr-Madan FFT → Vol Surface A, Greeks A
  → Path B: PINN forward pass (warm-started) → Vol Surface B, Greeks B
  → Comparator: D_σ(K,T), Greeks diff, Richness diff → log to DB

Step 4: Entry Decision (if no open position, and it's entry day)
  → Check: P_HV < τ_regime AND z_VRP > z_min AND Π/W > R_min
  → Strike selection uses Path A (primary)
  → Comparator records: would Path B have selected different strike?
  → If all pass: proceed to Step 5
  → If any fail: skip, wait for next entry day

Step 5: Risk Sizing
  → f_vol = σ_target / σ_portfolio
  → f_Kelly = clip(μ_hat / σ_hat², 0.2, 2.0)
  → f_DD = drawdown_override(DD_t)
  → f_final = min(f_vol, f_Kelly) × f_DD
  → N_spreads = floor(Account × f_final / MaxLoss)

Step 6: Execution
  → Place limit order for N_spreads at mid-price via IBKR

Step 7: Position Monitoring (daily for open positions)
  → Update Greeks via Path A (primary) and Path B (shadow)
  → Check: 75% profit? Stop loss? DTE ≤ 7? Regime emergency?
  → If any trigger: close position
  → Update DD level

Step 8: Comparator Daily Log
  → Record: Surface diff map, Greeks diff, strike agreement
  → Flag: any day where Path A and Path B disagree on entry/skip
  → Accumulate for monthly analysis
```

**Phase 1-2에서는 Step 3이 단순화된다:** BS closed-form으로 delta 계산, Path A/B 모두 비활성.

---

## 9. Backtest Framework — 3-Phase Validation

### 9.1 Phase 1: VIX Proxy Backtest

**Data:** VIX, VIX3M, SPX daily OHLCV, VVIX (2004-2025, ~20 years)

**Simulation Model:**

실제 옵션 거래를 시뮬레이션하지 않고, VRP의 대략적 P&L을 proxy로 계산:

$$r_{\text{proxy},t} = \frac{1}{\tau}\left(\frac{\text{VIX}_{t-\tau}^2}{252} - \text{RV}_{t}(\tau)^2 / 252\right) \times f_{\text{final},t-\tau}$$

이는 "τ일 전에 variance swap을 팔았을 때의 수익"에 대한 근사.

**검증 항목:**

| Metric | GO 기준 | NO-GO |
|--------|--------|-------|
| Regime-conditioned Sharpe | > 0.4 | ≤ 0.4 |
| MDD (regime-conditioned) | < 30% | ≥ 30% |
| Naive vs Regime Sharpe difference | > 0.1 | ≤ 0.1 |
| 2008 drawdown survival | < 25% | ≥ 25% |
| 2020 March drawdown | < 20% | ≥ 20% |
| Positive VRP months (%) | > 70% | ≤ 70% |

**Naive baseline:** Regime detection 없이, 매일 동일 exposure로 short vol. Regime이 추가하는 marginal value를 측정.

### 9.2 Phase 2: Options Chain Backtest

**Data:** Polygon.io SPX/SPY daily options snapshots

**Method:** 매주 실제 10-delta put spread를 구성하고 P&L을 정확히 계산:

$$\text{P\&L}_{\text{trade},i} = \Pi_i - \max(0, K_{1,i} - S_{T_i}) + \max(0, K_{2,i} - S_{T_i})$$

Transaction costs 포함:
- Commission: $0.65/contract (IBKR)
- Slippage: bid-ask spread의 25% (보수적 추정)

**검증 항목:**

| Metric | GO 기준 |
|--------|--------|
| Post-cost Sharpe | > 0.5 |
| MDD | < 25% |
| Win rate | > 75% |
| Average win / Average loss | > 0.3 |
| Phase 1 proxy vs Phase 2 actual 상관관계 | > 0.7 |

Phase 1과 Phase 2의 상관관계가 0.7 미만이면 — proxy 모델이 신뢰할 수 없다는 의미. Phase 1 결과를 의심해야 한다.

### 9.3 Phase 3: Dual-Path Comparator Validation

**Prerequisites:** Phase 2 GO verdict. Options chain data 가용.

**Method:** 동일 기간, 동일 데이터에 대해 Path A와 Path B를 각각 실행하여 비교.

**Step 1 — PINN Baseline Validation:**

교수님 연구 경로를 따라 PINN의 기본 능력을 먼저 검증:

| Test | Input | Ground Truth | GO 기준 |
|------|-------|-------------|--------|
| 1D Heat + Gaussian IC | $g(x) = e^{-50(x-0.5)^2}$ | Fourier analytic solution | L2 error < $10^{-4}$ |
| BS → Heat → BS roundtrip | BS put payoff 변환 | BS closed-form | Price error < $0.01 |
| Market data fit (1 day) | SPX chain, 1 trading day | Market prices | RMSE < market bid-ask spread |

Step 1을 통과해야 Step 2로 진행. PINN이 heat equation도 못 풀면 vol surface 학습도 신뢰할 수 없다.

**Step 2 — Surface Comparison (Static):**

특정 거래일의 options chain에 대해 Path A와 Path B를 각각 calibrate/train하고 비교:

| Metric | 측정 방법 | 기대 |
|--------|----------|------|
| Surface RMSE (A vs mkt) | $\sqrt{\text{mean}(\sigma_A - \sigma_{\text{mkt}})^2}$ across strikes | Heston baseline |
| Surface RMSE (B vs mkt) | $\sqrt{\text{mean}(\sigma_B - \sigma_{\text{mkt}})^2}$ across strikes | PINN ≤ Heston |
| OTM Put region RMSE | 위와 동일, $K/S < 0.93$ 영역만 | PINN < Heston (가설) |
| PDE residual (B) | $\text{mean}|\mathcal{L}_{\text{PDE}}|$ | < $10^{-4}$ |
| Arb violation (B) | butterfly/calendar violations 수 | 0 |

**Step 3 — Dynamic Backtest Comparison:**

6개월 이상의 기간에 대해 매주 거래를 시뮬레이션:

| Metric | 계산 | 의의 |
|--------|------|------|
| Strike agreement rate | $K_{1,A}(t) = K_{1,B}(t)$인 비율 | 두 모델이 같은 거래를 하는가 |
| $\Delta$Sharpe ($B - A$) | Sharpe 차이 | PINN이 P&L을 개선하는가 |
| $\Delta$MDD ($B - A$) | MDD 차이 | PINN이 risk를 줄이는가 |
| Regime-conditional $\Delta$Sharpe | Regime별 분해 | 어떤 환경에서 차이가 나는가 |
| Entry/skip disagreement | A는 진입하고 B는 skip (또는 반대) | 가장 중요한 차이 |

**Phase 3 결론 분류:**

| 결과 | 해석 | Action |
|------|------|--------|
| Strike agreement > 90%, $\Delta$Sharpe ≈ 0 | 두 모델이 실질적으로 동일한 결론 | Path B는 validation 역할 유지. 논문: "PINN이 Heston과 동등함을 확인" |
| Strike agreement < 80%, $\Delta$Sharpe > 0.05 | PINN이 실질적으로 더 나은 pricing | Path B를 primary 승격 검토. 논문: "PINN이 OTM put pricing에서 Heston을 개선" |
| Strike agreement < 80%, $\Delta$Sharpe < -0.05 | PINN이 더 나쁜 pricing | PINN training 개선 필요. 논문: "현재 PINN 아키텍처의 한계 분석" |
| Regime-conditional 차이 발견 | 특정 regime에서만 PINN 우위 | Hybrid switching 전략 개발. 논문: "Regime-dependent model selection" |

어떤 결과가 나오든 논문이 된다. 이것이 dual-path의 핵심 가치이다.

### 9.4 Overfitting Defense

축구 프로젝트와 동일한 원칙:

**CPCV (Combinatorially Purged Cross-Validation):**
- $N = 5$ groups, $k = 2$ test → $C(5,2) = 10$ splits
- Embargo: 5 trading days (options은 주간 주기이므로)

**PBO (Probability of Backtest Overfitting):**
- PBO < 5% 기준

**Parameter Sensitivity:**
- Regime thresholds, spread width, DTE range, delta target를 ±20% 변동시켜도 Sharpe이 ±30% 이내

---

## 10. Parameter Reference

| Parameter | Value | Layer | Tunable |
|-----------|-------|-------|---------|
| **VRP Measurement** | | | |
| RV window | 21 days | L0 | No |
| VRP z-score window | 252 days | L0 | No |
| VRP z-score entry min | -1.0 | L0 | [-2.0, 0.0] |
| **Regime Detection** | | | |
| HMM states | 3 | L1 | No |
| HMM features | 5 (RV, VIX, TS, VVIX, ΔVol) | L1 | No |
| HMM min window | 504 days | L1 | No |
| HMM n_init | 10 | L1 | No |
| Label stability threshold | ≥ 90% | L1 | No |
| XGBoost estimators / depth | 200 / 4 | L1 | No |
| Brier score threshold | < 0.25 | L1 | No |
| **Path A: Fourier Pricing** | | | |
| Heston parameters | $(v_0, \kappa, \theta, \sigma_v, \rho)$ | L2-A | Calibrated daily |
| FFT grid points | 4096 | L2-A | No |
| Carr-Madan damping α | 1.5 | L2-A | No |
| Calibration optimizer | DE → LM | L2-A | No |
| Vega weighting | Yes | L2-A | No |
| **Path B: PINN Pricing** | | | |
| Network depth | 4-6 layers | L2-B | [3, 8] |
| Neurons per layer | 64-128 | L2-B | [32, 256] |
| Activation | tanh | L2-B | No (smooth required) |
| $\lambda_1$ (data) | 1.0 | L2-B | No |
| $\lambda_2$ (PDE) | 0.1 → ramp to 10.0 | L2-B | Schedule tunable |
| $\lambda_3$ (arb) | 1.0 | L2-B | No |
| $\lambda_4$ (BC) | 1.0 | L2-B | No |
| Collocation points $N_r$ | 10,000 | L2-B | [5K, 50K] |
| Training epochs (cold) | 50,000 | L2-B | No |
| Training epochs (warm) | 5,000 | L2-B | No |
| Learning rate | $10^{-3}$ → cosine to $10^{-5}$ | L2-B | No |
| PDE residual target | < $10^{-4}$ | L2-B | No |
| **Comparator** | | | |
| Primary path | Path A (Fourier) | Comp | No (until Phase 5) |
| Surface diff logging | Daily | Comp | No |
| Strike agreement threshold | 80% (meaningful diff) | Comp | No |
| $\Delta$Sharpe significance | 0.05 | Comp | No |
| Min evaluation period | 6 months | Comp | No |
| **Strategy** | | | |
| Underlying | SPX | L3 | No |
| Strategy type | Put credit spread | L3 | No |
| Target DTE | 30-45 days | L3 | No |
| Short leg delta | 10-delta | L3 | [5, 16] |
| Spread width W | $50-$100 | L3 | [$25, $150] |
| Entry frequency | Weekly | L3 | No |
| Profit target | 75% of premium | L3 | [50%, 90%] |
| Stop loss | 2× premium | L3 | [1.5×, 3×] |
| Close DTE threshold | ≤ 7 days | L3 | No |
| Min premium ratio Π/W | 10% | L3 | [5%, 15%] |
| P_HighVol full position | < 0.2 | L3 | No |
| P_HighVol half position | 0.2 - 0.5 | L3 | No |
| P_HighVol skip | > 0.5 | L3 | No |
| P_HighVol emergency close | > 0.8 | L3 | No |
| **Risk Management** | | | |
| σ_target | 12% annualized | L4 | No |
| Vol scaling max | 1.5× | L4 | No |
| Vol scaling min | 0.3× | L4 | No |
| Kelly shrinkage α | 0.6 | L4 | [0.4, 0.8] |
| Kelly μ_prior (LV/NV/HV) | 15% / 8% / 2% | L4 | [5%, 20%] |
| Kelly clip | [0.2×, 2.0×] | L4 | No |
| Kelly rolling window | 60 days | L4 | No |
| DD warn | 5% | L4 | No |
| DD reduce (half) | 5% | L4 | No |
| DD kill | 10% | L4 | No |
| **Backtest Validation** | | | |
| Phase 1 GO: Sharpe | > 0.4 | BT | No |
| Phase 1 GO: MDD | < 30% | BT | No |
| Phase 2 GO: Post-cost Sharpe | > 0.5 | BT | No |
| Phase 2 GO: MDD | < 25% | BT | No |
| Phase 2 GO: Win rate | > 75% | BT | No |
| Phase 3 PINN baseline: Heat L2 | < $10^{-4}$ | BT | No |
| Phase 3 PINN baseline: BS roundtrip | < $0.01 | BT | No |
| Phase 3 Surface RMSE (B ≤ A) | OTM put region | BT | No |
| CPCV groups / test | N=5, k=2 | BT | No |
| Embargo | 5 days | BT | No |
| PBO threshold | < 5% | BT | No |
| Parameter sensitivity | ±30% Sharpe | BT | No |
