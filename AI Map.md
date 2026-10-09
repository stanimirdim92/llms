# AI Map

**One central place for AI.**

A curated route through the best free and paid material for becoming an AI engineer, from first concepts to shipping agents in production, plus the blogs and people worth following. Every link was opened and checked in October 2026.

Online version with progress tracking: https://claude.ai/artifact/5KRkq84PEj5zvbtbBnqmzj

Offline copy: `AI Map.html` in this folder (progress saved in that browser only).

## How to read this

- **Do these**: the main path. **Alternatives** cover the same ground, so pick at most one. **Optional** adds depth. **Reference** is for lookups.
- **Builder track** (ship LLM apps, RAG and agents) skips Stages 4–6 and uses a lighter ML foundation: about **338 h** of core material, roughly 8 months at 10 h/week.
- **Full track** (also understand and train models) includes every stage: about **658 h**, roughly 15 months at 10 h/week.
- Items with a different role per track say so in italics.
- In the HTML version, click an item's circle to move it from Not started to In progress to Done. In this file, use `- [ ]` and `- [x]`, and add `🚧` after an item's title to mark it in progress.

## Stage 0: Orientation

~16 h of core material (Full track).

Get the vocabulary and a mental model of what LLMs are before you write code. This stage is short on purpose.

### Do these

- [ ] **[Generative AI for Everyone](https://www.coursera.org/learn/generative-ai-for-everyone)**  
  DeepLearning.AI · Andrew Ng · Course · ~6 h · Audit free  
  How LLMs work and where they fail; prompting, RAG and fine-tuning at a concept level; the GenAI project lifecycle. _The natural sequel to AI For Everyone. Take this instead of the Google AI cert and the IBM GenAI article._
- [ ] **[Neural networks series](https://www.youtube.com/watch?v=aircAruvnKk&list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi)**  
  3Blue1Brown · Video series · ~4 h · Free  
  Animated explanations of gradient descent, backprop, transformers, attention and how LLMs store facts. _The best intuition builder on the list. Chapters 5–7 (2024) cover transformers._
- [ ] **[Karpathy: Intro to LLMs and Deep Dive into LLMs](https://www.youtube.com/@AndrejKarpathy/videos)**  
  Andrej Karpathy · Talks · ~5 h · Free  
  Non-coding talks on how ChatGPT-style models are pretrained, fine-tuned and used. Start with the 1-hour 'Intro to Large Language Models', then the 3.5-hour 'Deep Dive into LLMs like ChatGPT' (2025). _The same channel hosts Zero to Hero, which is in Stage 5._
- [ ] **[The AI Engineering Skills Map](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map)**  
  Andrew Ng · The Batch · Article series · ~1 h · Free  
  Ng's map of the AI engineer's job, built from 10,000+ job postings. It has four pillars: building and deploying AI apps, software fundamentals, using coding agents, and shaping the build. _Use it as the rubric for this route. Parts 3 and 5 are linked from side tracks B and C below._ Also: [Part 2: AI applications](https://www.deeplearning.ai/the-batch/he-ai-engineering-skills-map-in-detail-building-and-deploying-ai-applications), [Part 4: Coding agents](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map-in-detail-using-coding-agents)

### Optional depth

- [ ] **[AI For Everyone](https://www.coursera.org/learn/ai-for-everyone/)**  
  DeepLearning.AI · Andrew Ng · Course · ~7 h · Audit free  
  Non-technical intro to what ML can do, AI projects and strategy. _From 2019, before generative AI. Take it if you're new to AI or manage AI projects. Otherwise go straight to Generative AI for Everyone._
- [ ] **[What is generative AI?](https://research.ibm.com/blog/what-is-generative-AI)**  
  IBM Research · Article · ~0.5 h · Free  
  A history from VAEs to transformers, plus instruction tuning and RLHF. _From 2023, before agents and reasoning models. The 3Blue1Brown series covers this better._
- [ ] **[Google AI Professional Certificate](https://coursera.org/professional-certificates/google-ai)**  
  Google · Certificate · ~8 h · Paid  
  Eight short courses on using Gemini and Workspace at work: prompting, research, vibe-coding simple apps. _Teaches AI use, not AI building, and overlaps the two Andrew Ng intros._
- [ ] **[How Transformer LLMs Work](https://www.deeplearning.ai/courses/how-transformer-llms-work)** _(Full track: optional · Builder track: core)_  
  DeepLearning.AI · Jay Alammar & Maarten Grootendorst · Short course · ~2 h · Free to watch  
  Visual walk-through of tokenizers, embeddings, attention, transformer blocks, KV cache and MoE. _The LLM internals a builder needs, in under 2 hours. Optional on the Full track, since Stage 5 goes much deeper._

### Reference

- [ ] **[What is machine learning?](https://www.ibm.com/think/topics/machine-learning)**  
  IBM Think · Article · ~1 h · Free  
  A long, current explainer on learning paradigms, architectures and MLOps. _Updated October 2026. Read once._

**Build:** Write a one-page explainer for a colleague covering tokens, training versus inference, and when you would use RAG, fine-tuning or an agent.

**Move on when:** You can explain how a transformer predicts the next token, and why models hallucinate.

## Stage 1: Python and math footing

~44 h of core material (Full track).

Write idiomatic Python, including OOP, comprehensions, venv and packages, and handle data with NumPy and pandas. Pick up just enough linear algebra to read ML code. Skip whatever you already know.

### Do these

- [ ] **[Python Programming MOOC](https://programming-23.mooc.fi/)**  
  University of Helsinki · Course · ~40 h · Free  
  14 parts from basics through OOP (your link was Part 9.3, Encapsulation), with auto-graded exercises. _Linked here at the course root. Skim the parts you know and do the OOP parts (8–10) properly._ Also: [Your original link (9.3)](https://programming-23.mooc.fi/part-9/3-encapsulation)
- [ ] **[Essence of Linear Algebra](https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab)**  
  3Blue1Brown · Video series · ~4 h · Free  
  Visual intuition for vectors, matrices, dot products and transforms, which is the math under every layer. _The fastest way to the linear algebra under every layer._

### Alternatives (pick at most one)

- [ ] **[AI Python for Beginners](https://www.coursera.org/learn/ai-python-for-beginners)**  
  DeepLearning.AI · Andrew Ng · Course · ~20 h · Free on deeplearning.ai  
  Python from zero through small LLM-powered projects, with an AI tutor. _Gentler and more AI-flavoured than the Helsinki MOOC but shallower. Pick one._
- [ ] **[Python for Data Science, AI & Development](https://www.coursera.org/learn/python-for-applied-data-science-ai)**  
  IBM · Course · ~25 h · Audit free  
  Python basics, pandas, NumPy, REST APIs and scraping in Jupyter. _Course 4 of the IBM GenAI cert. Only needed if you don't know Python yet._
- [ ] **[Mathematics for Machine Learning](https://www.coursera.org/specializations/mathematics-machine-learning)** _(Full track: alternative · Builder track: skip)_  
  Imperial College London · Specialization · ~60 h · Audit free  
  Linear algebra, multivariate calculus and PCA, aimed at ML. _Only needed on the Full track, if the math in Stages 4–6 feels shaky._

### Optional depth

- [ ] **[Data Analysis with Python](https://www.coursera.org/learn/data-analysis-with-python)**  
  IBM · Course · ~16 h · Audit free  
  Wrangling, EDA and regression with pandas and scikit-learn. _Good pandas practice. Its regression part repeats Ng's ML course 1._
- [ ] **[Mathematics for Machine Learning and Data Science](https://www.deeplearning.ai/specializations/mathematics-for-machine-learning-and-data-science)** _(Full track: optional · Builder track: skip)_  
  DeepLearning.AI · Luis Serrano · Specialization · ~94 h · DLAI Pro  
  Linear algebra, calculus, probability and statistics, with Python labs. _Friendlier than the Imperial specialization, which is now listed as its alternative. Only needed if the math in Stages 4–6 feels shaky._
- [ ] **[Automate the Boring Stuff with Python (3rd ed.)](https://automatetheboringstuff.com/)**  
  Al Sweigart · Free book · ~20 h · Free  
  Practical scripting: files, web scraping, spreadsheets and PDFs, scheduling, GUI automation. _The 3rd edition is current. Use it as a practical companion to the Helsinki MOOC._
- [ ] **[Software Design by Example](https://third-bit.com/sdxpy/intro/)**  
  Greg Wilson · Free book · ~30 h · Free  
  Learn design by building small versions of real tools: an interpreter, a test runner, a database, a web server. _From 2024. Nothing else on the route teaches software design, so read it after the MOOC to write better Python._
- [ ] **[Kaggle Learn](https://www.kaggle.com/learn)**  
  Kaggle · Micro-courses · ~8 h · Free  
  In-browser 3–5 hour courses: pandas, data cleaning, feature engineering, data viz, plus Google's self-paced GenAI and Agents intensives. _Do the pandas and feature-engineering ones before Stage 3. The ML and agent ones repeat what's on the route._

### Reference

- [ ] **[free-programming-books: Python courses](https://github.com/EbookFoundation/free-programming-books/blob/main/courses/free-courses-en.md#python)**  
  EbookFoundation · Link list · Free  
  About 50 free Python courses, including Django, Flask and FastAPI. _A directory, not a path. Use it to find alternatives._
- [ ] **[Comprehensive Python Cheatsheet](https://github.com/gto76/python-cheatsheet)**  
  gto76 · Reference · Free  
  The whole language on one page, and still maintained in 2026. _Keep it open while you code._
- [ ] **[Hypermodern Python](https://blog.claudiojolowicz.com/posts/hypermodern-python-01-setup/)**  
  Claudio Jolowicz · Article series · Free  
  A six-part guide to project setup, testing, linting, typing, docs and CI. _The ideas hold up, but the tools are from 2020. Use uv and ruff instead of Poetry, pyenv and flake8._
- [ ] **[Python Design Patterns and wtfpython](https://python-patterns.guide/)**  
  Brandon Rhodes · Satwik Kansal · Reference · Free  
  Idiomatic patterns for Python, plus a catalogue of surprising language gotchas with explanations. _Good for depth, not required._ Also: [wtfpython](https://github.com/satwikkansal/wtfpython)
- [ ] **[copier-astral](https://github.com/ritwiktiwari/copier-astral)**  
  Ritwik Tiwari · Project template · Free  
  Scaffolds a Python project with uv, ruff, ty, pytest, MkDocs, GitHub Actions and Docker. _The modern toolchain from the start, instead of setting it up by hand._

**Build:** Write a script that pulls JSON from a public API, cleans it with pandas, and saves a chart and a CSV.

**Move on when:** You can write a small package with classes and tests without looking things up, and you can explain a matrix multiply.

## Stage 2: Build with LLM APIs

~27 h of core material (Full track).

Ship useful things on top of hosted models early: prompting, structured output, tool calls, embeddings. This keeps you motivated while the theory comes later.

### Do these

- [ ] **[Building software on top of LLMs (PyCon 2025)](https://building-with-llms-pycon-2025.readthedocs.io/en/latest/)**  
  Simon Willison · Workshop · ~4 h · Free (API costs)  
  Hands-on with the llm library: prompting from Python, text-to-SQL, structured extraction, embeddings/RAG, tool use and prompt injection. _The best practical first step on the map, and it takes about 3 hours._
- [ ] **[Anthropic courses](https://github.com/anthropics/courses)**  
  Anthropic · Notebooks · ~8 h · Free (API costs)  
  Notebook courses on API fundamentals, prompt engineering, real-world prompting, prompt evaluations and tool use. _Added because it covers evals and tool use from a model provider's point of view._
- [ ] **[Prompt_Engineering](https://github.com/NirDiamant/Prompt_Engineering)**  
  Nir Diamant · Notebooks · ~12 h · Free  
  22 notebooks: zero/few-shot, chain-of-thought, self-consistency, decomposition, prompt security. _Active as of September 2026. Skim the basics and spend your time on the security and decomposition notebooks._
- [ ] **[Pydantic for LLM Workflows](https://www.deeplearning.ai/courses/pydantic-for-llm-workflows)**  
  DeepLearning.AI · Ryan Keenan · Short course · ~2 h · Free to watch  
  Validated structured outputs and tool-call data with Pydantic. _Exactly what the Stage 2 project needs, and it's vendor-neutral._
- [ ] **[Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/)**  
  Hamel Husain · Article · ~0.5 h · Free  
  Three levels of evals: assertion-style unit tests, human and LLM-judge review of logged traces, and A/B tests. Plus why reading your own data is the core habit. _Ng calls eval-driven development the skill that separates strong AI engineers. Start the habit here, not in Stage 9._
- [ ] **[AI Engineering (book) and its companion repo](https://github.com/chiphuyen/aie-book)**  
  Chip Huyen · O'Reilly · Book + notes · Book paid, notes free  
  The standard book for this role: foundation models, evaluation, prompt engineering, RAG, agents, finetuning, dataset engineering, inference optimization and feedback loops. The repo has the table of contents, chapter summaries, study notes and resources. _It covers concepts rather than tools, so it ages well. Read the chapters alongside Stages 2 and 7–9. The chapter summaries are free even without the book._

### Optional depth

- [ ] **[Learn Prompting](https://learnprompting.org/)**  
  Learn Prompting · Docs · Freemium  
  Prompting docs plus a strong prompt-hacking and red-teaming section. _Duplicates promptingguide.ai except for the security angle._
- [ ] **[Generative AI: Prompt Engineering Basics](https://www.coursera.org/learn/generative-ai-prompt-engineering-for-everyone)** _(Full track: optional · Builder track: skip)_  
  IBM · Course · ~9 h · Audit free  
  Prompting techniques in chat UIs, with no API work. _Course 3 of the IBM GenAI cert. Below the level of the core items here._
- [ ] **[Building Generative AI-Powered Applications with Python](https://www.coursera.org/learn/building-gen-ai-powered-applications)**  
  IBM · Course · ~15 h · Audit free  
  Seven small projects: image captioner, chatbot, voice assistant, RAG and more, built with Gradio and Flask. _The best early IBM course, but some of its models (GPT-3, Llama 2) are dated._
- [ ] **[Developing AI Applications with Python and Flask](https://www.coursera.org/learn/python-project-for-ai-application-development)**  
  IBM · Course · ~12 h · Audit free  
  Flask, unit tests, packaging and deployment around Watson NLP. _Mostly general web development. Skip it if you already build web apps._
- [ ] **[Getting Structured LLM Output](https://www.deeplearning.ai/courses/getting-structured-llm-output)**  
  DeepLearning.AI × DotTxt · Short course · ~1.5 h · Free to watch  
  Covers JSON modes, re-prompting and constrained decoding with Outlines. _Explains how structured generation works under the hood._
- [ ] **[Safety system messages](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/system-message)**  
  Microsoft Learn · Docs · ~0.5 h · Free  
  How to write, iterate on and test system prompts, with their safety techniques and limits. _A short, mostly vendor-neutral checklist._

### Reference

- [ ] **[DeepLearning.AI Learning Platform (My Learnings)](https://learn.deeplearning.ai/my/learnings)**  
  DeepLearning.AI + partners · Course platform · ~8 h · Freemium  
  1–2 hour hands-on courses on prompting, RAG, agents, evals and fine-tuning, made with OpenAI, Anthropic, LangChain, Hugging Face and others. _Your own dashboard of courses in progress once you're signed in. The full catalogue has 131 items. The 25 worth taking are placed in their stages on this map, and the rest are mostly thin partner showcases or superseded 2023–24 courses. Short courses are free to watch, while the longer courses and certificates need DeepLearning.AI Pro._ Also: [Course catalogue](https://www.deeplearning.ai/courses/)
- [ ] **[Prompt Engineering Guide](https://www.promptingguide.ai/)**  
  DAIR.AI · Docs · Free  
  A full catalogue of prompting techniques, agents, context engineering and risks, with papers. _Kept current (2026). Use it as a lookup, not to read cover to cover._
- [ ] **[Artificial Analysis](https://artificialanalysis.ai/)**  
  Artificial Analysis · Leaderboard · Free  
  Independent comparison of models and API providers on intelligence, speed, latency and price. _Where to look when choosing a model for a project. Nothing else on the route covers this._
- [ ] **[OpenAI Cookbook](https://github.com/openai/openai-cookbook)**  
  OpenAI · Notebooks · Free (API costs)  
  Runnable examples for tool calling, structured outputs, embeddings, RAG, agents and evals. _The OpenAI counterpart to the Anthropic courses. Look things up here rather than working through it._
- [ ] **[Claude Cookbooks](https://github.com/anthropics/claude-cookbooks)**  
  Anthropic · Notebooks · Free (API costs)  
  Official notebooks for tool use, RAG, extended thinking, multimodal, agent patterns, the Agent SDK, skills, observability and cost optimization. _The Claude counterpart to the OpenAI Cookbook, and very active. Look recipes up here as you need them._

**Build:** Build a CLI that turns messy text (emails, invoices, logs) into validated JSON with Pydantic, and include an eval set of 20 examples.

**Move on when:** You can pick zero-shot, few-shot or chain-of-thought for a task, explain a prompt injection risk in your own app, and show the failure categories you found by reading 50 real outputs before changing the prompt.

## Stage 3: Machine learning foundations

~67 h of core material (Full track).

Learn the classic ML loop: features, loss, gradient descent, overfitting, evaluation. On the Builder track the faster Google crash course is enough.

### Do these

- **[Machine Learning Specialization](https://www.coursera.org/specializations/machine-learning-introduction)** _(Full track: core · Builder track: optional)_  
  DeepLearning.AI & Stanford · Andrew Ng · Specialization · Audit free  
  Three courses in Python: regression, classification, neural nets in TensorFlow, trees and XGBoost, clustering, recommenders, intro RL. _The 2022 Python remake of Ng's classic, rated 4.9. Its three courses are listed below._
  - [ ] **[1 · Supervised ML: Regression and Classification](https://www.coursera.org/learn/machine-learning)** _(Full track: core · Builder track: optional)_  
    Andrew Ng · Course · ~33 h · Audit free  
    Cost functions, gradient descent, logistic regression, regularization.
  - [ ] **[2 · Advanced Learning Algorithms](https://www.coursera.org/learn/advanced-learning-algorithms)** _(Full track: core · Builder track: optional)_  
    Andrew Ng · Course · ~34 h · Audit free  
    Neural nets in TensorFlow, bias/variance, error analysis, random forests, XGBoost.

### Alternatives (pick at most one)

- [ ] **[Machine Learning Crash Course](https://developers.google.com/machine-learning/crash-course)** _(Full track: alternative · Builder track: core)_  
  Google · Course · ~15 h · Free  
  Fast, interactive tour of regression, classification, data prep, neural nets, embeddings, LLM basics and production ML. _Refreshed in 2024. It's enough ML for the Builder track._
- [ ] **[Machine Learning with Python](https://www.coursera.org/learn/machine-learning-with-python)**  
  IBM · Course · ~20 h · Audit free  
  Survey of classical ML in scikit-learn, ending in a project. _Covers the same ground as Ng's specialization with more sklearn and less intuition. Take one._
- [ ] **[IBM Machine Learning Professional Certificate](https://www.coursera.org/professional-certificates/ibm-machine-learning)**  
  IBM · Certificate · ~120 h · Paid  
  Six courses: EDA, regression, classification, unsupervised, intro DL/RL in Keras, capstone. _Overlaps Ng's ML Specialization. Take it only if you want the IBM credential._
- [ ] **[Applied Machine Learning Specialization](https://www.coursera.org/specializations/applied-machine-learning)**  
  Johns Hopkins · Specialization · ~55 h · Paid  
  Three courses of Kaggle-style ML projects, ending in CNNs and RL. _A university-branded alternative with nothing unique._
- **[ML with Scikit-learn, PyTorch & Hugging Face](https://www.coursera.org/professional-certificates/machine-learning-scikit-learn-pytorch-hugging-face)**  
  Coursera · industry instructors · Certificate · ~137 h · Paid  
  Five courses: sklearn ML, advanced techniques, PyTorch DL, Hugging Face GenAI, end-to-end project. _A modern stack in one package that covers Stages 3–5 at a lighter depth. The instructors aren't named._
  - [ ] **[1 · Foundations of Machine Learning](https://www.coursera.org/learn/foundations-of-machine-learning-1)**  
    Coursera · industry instructors · Course · ~30 h · Coursera Plus  
    Supervised and unsupervised learning, preprocessing and feature engineering, and time-series forecasting (ARIMA, Holt-Winters, Prophet) in scikit-learn and statsmodels. _Course 1 of the certificate above. Its time-series module is the only part Ng's ML Specialization doesn't cover. Only 20 reviews so far._

### Optional depth

- [ ] **[3 · Unsupervised Learning, Recommenders, RL](https://www.coursera.org/learn/unsupervised-learning-recommenders-reinforcement-learning)**  
  Andrew Ng · Course · ~28 h · Audit free  
  Clustering, anomaly detection, collaborative filtering, deep Q-learning. _Useful, but not on the critical path._
- [ ] **[ML From Scratch](https://www.python-engineer.com/courses/mlfromscratch/01_knn/)**  
  Python Engineer · Patrick Loeber · Video series · ~10 h · Free  
  Implements KNN, regression, Naive Bayes, SVM, trees, PCA and K-Means in NumPy. _The site was intermittently unavailable in October 2026. The code is mirrored at github.com/patrickloeber/MLfromscratch._ Also: [GitHub mirror](https://github.com/patrickloeber/MLfromscratch)
- [ ] **[CS50's Introduction to AI with Python](https://pll.harvard.edu/course/cs50s-introduction-artificial-intelligence-python)**  
  Harvard · Malan & Yu · Course · ~70 h · Free  
  Project-heavy classical AI: search, logic, probability, optimization, ML, RL, neural nets, NLP. _Covers search and logic, which none of the ML certs do. It's weak on LLMs._
- [ ] **[Cynthia Rudin's channel](https://www.youtube.com/@cynthiarudinduke/videos)**  
  Duke · Cynthia Rudin · Talks · Free  
  Research talks on interpretable ML, plus lectures for her free textbook 'Intuition for the Algorithms of Machine Learning'. _For interpretability depth. It's not a course._
- [ ] **[mlcourse.ai](https://mlcourse.ai/book/index.html)**  
  Yury Kashnitsky · Course · ~40 h · Free  
  Ten topics of classic ML with assignments: trees, linear models, ensembles, gradient boosting, time series. _Only adds depth beyond Ng on boosting and time series._
- [ ] **[Exploratory Data Analysis for Machine Learning](https://www.coursera.org/learn/ibm-exploratory-data-analysis-for-machine-learning)**  
  IBM · Course · ~14 h · Coursera Plus  
  Retrieving and cleaning data, EDA and feature engineering, then inferential statistics: hypothesis tests, p-values, Type I and II errors. _Course 1 of the IBM ML certificate. Its hypothesis-testing module fills a real gap, since you need it to tell whether an eval or A/B difference is real (Track C)._

**Build:** Take a Kaggle tabular dataset from EDA to a tuned XGBoost model, with a proper validation split and a short write-up.

**Move on when:** You can explain bias versus variance and choose the right metric for an imbalanced classifier.

## Stage 4: Deep learning _(Full track only)_

~115 h of core material (Full track).

Learn how neural networks actually train: backprop, optimizers, regularization, CNNs and sequence models. Do it in PyTorch, because the LLM tooling is PyTorch.

### Do these

- [ ] **[PyTorch in One Hour](https://sebastianraschka.com/teaching/pytorch-1h/)**  
  Sebastian Raschka · Tutorial · ~2 h · Free  
  Tensors, autograd, training loop, DataLoader, saving models, multi-GPU DDP. _Do this first. It is also Appendix A of his LLMs-from-scratch book._
- **[Deep Learning Specialization](https://www.coursera.org/specializations/deep-learning)**  
  DeepLearning.AI · Andrew Ng · Specialization · Audit per course  
  Five courses: NNs from scratch, tuning, ML strategy, CNNs, sequence models up to transformers. _Last updated in 2021, so it has no modern LLM content. Audit the individual courses below for free._
  - [ ] **[1 · Neural Networks and Deep Learning](https://www.coursera.org/learn/neural-networks-deep-learning)**  
    Andrew Ng · Course · ~25 h · Audit free  
    Vectorized forward and backward propagation in NumPy, shallow and deep nets.
  - [ ] **[2 · Improving Deep Neural Networks](https://www.coursera.org/learn/deep-neural-network)**  
    Andrew Ng · Course · ~24 h · Audit free  
    Regularization, initialization, Adam, batch norm, hyperparameter search.
  - [ ] **[3 · Structuring ML Projects](https://www.coursera.org/learn/machine-learning-projects)**  
    Andrew Ng · Course · ~7 h · Audit free  
    Metrics, error analysis, data mismatch, transfer learning. _Short and useful even on the Builder track._
  - [ ] **[5 · Sequence Models](https://www.coursera.org/learn/nlp-sequence-models)**  
    Andrew Ng · Course · ~37 h · Audit free  
    RNNs, LSTMs, word embeddings, attention, intro to transformers. _Don't skip it, because it is the bridge to Stage 5._
- [ ] **[MIT 6.S191: Introduction to Deep Learning](https://introtodeeplearning.com/)**  
  MIT · Amini & Amini · Course · ~20 h · Free  
  Fast bootcamp from fundamentals through generative models, RL and LLMs, with three code labs. _The 2026 edition is the most current deep learning course on the map._

### Alternatives (pick at most one)

- [ ] **[Practical Deep Learning for Coders](https://course.fast.ai/Lessons/lesson1.html)**  
  fast.ai · Jeremy Howard · Course · ~40 h · Free  
  Top-down and code-first: train real models from lesson 1, then learn how they work. Part 2 builds Stable Diffusion. _A practical alternative to Ng's DL specialization. It's from 2022 and centred on the fastai library. The YouTube playlist is the same course._ Also: [YouTube playlist](https://www.youtube.com/playlist?list=PLfYUBJiXbdtSvpQjSnJJ_PmDQB_VyT5iU)
- [ ] **[Convolutional Neural Networks in TensorFlow](https://www.coursera.org/learn/convolutional-neural-networks-tensorflow)**  
  DeepLearning.AI · Laurence Moroney · Course · ~17 h · Audit free  
  Real-world image data, augmentation, transfer learning and multiclass classification in TensorFlow and Keras. _Course 2 of the TensorFlow Developer certificate. More hands-on than Ng's CNN course, but in TensorFlow while the rest of the route uses PyTorch. Pick one._

### Optional depth

- [ ] **[4 · Convolutional Neural Networks](https://www.coursera.org/learn/convolutional-neural-networks)**  
  Andrew Ng · Course · ~36 h · Audit free  
  ResNets, YOLO, U-Net, face recognition, style transfer. _Skip it unless you care about computer vision._
- [ ] **[NYU Deep Learning (Spring 2021)](https://atcold.github.io/NYU-DLSP21/)**  
  NYU · LeCun & Canziani · Course · ~60 h · Free  
  Graduate-level: energy-based models, self-supervised learning, GNNs, attention. _Theory depth for later. It's light on LLMs._
- [ ] **[Full Stack Deep Learning 2022](https://fullstackdeeplearning.com/course/2022/)**  
  FSDL · Karayev, Tobin, Frye · Course · ~20 h · Free  
  The engineering around DL products: tooling, testing, data, deployment, monitoring, teams. _Some tools are from 2022. Its LLM Bootcamp (2023) is the newer follow-up._
- [ ] **[PyTorch for Deep Learning Professional Certificate](https://www.deeplearning.ai/specializations/pytorch-for-deep-learning-professional-certificate)**  
  DeepLearning.AI · Laurence Moroney · Certificate · ~88 h · DLAI Pro  
  Building, optimizing and deploying deep learning models in PyTorch. _Ng's DL specialization is TensorFlow/NumPy, so take selected modules from this if PyTorch still feels unfamiliar after the one-hour primer._
- [ ] **[Neural Networks and Deep Learning](http://neuralnetworksanddeeplearning.com/)**  
  Michael Nielsen · Free book · ~15 h · Free  
  Derives backprop and builds an MNIST classifier in NumPy, explaining every step. _Very clear on intuition. The code is dated (last updated 2019), and Karpathy's micrograd covers the same ground._
- [ ] **[An overview of gradient descent optimization algorithms](https://www.ruder.io/optimizing-gradient-descent/)**  
  Sebastian Ruder · Article · ~1 h · Free  
  Momentum, Adagrad, RMSprop and Adam compared side by side. _Still the clearest single read on optimizers. It predates AdamW._

### Reference

- [ ] **[Dive into Deep Learning (D2L)](https://d2l.ai/index.html)**  
  Zhang, Lipton, Li, Smola · Book · Free  
  An interactive textbook where every section is a runnable notebook, from basics to transformers. _Use it as the textbook alongside whichever course you take._
- [ ] **[Deep Learning (Goodfellow, Bengio, Courville)](https://www.deeplearningbook.org/)**  
  MIT Press · Textbook · Free online  
  A theory-heavy reference on DL math, regularization, optimization and classic architectures. _From 2016, with no transformers. Use it to look up theory, not to read through._

**Build:** Fine-tune a pretrained vision or text model in plain PyTorch, with your own training loop and learning-rate schedule.

**Move on when:** You can write a training loop from memory and debug a loss that won't go down.

## Stage 5: Transformers and LLM internals _(Full track only)_

~100 h of core material (Full track).

Build a GPT from scratch, then learn the Hugging Face stack that real work happens in.

### Do these

- [ ] **[Neural Networks: Zero to Hero](https://www.youtube.com/playlist?list=PLAqhIrjkxbuWI23v9cThsA9GvCAUhRvKZ)**  
  Andrej Karpathy · Video series · ~20 h · Free  
  Code along as Karpathy builds micrograd, makemore, a GPT and a BPE tokenizer from scratch, then reproduces GPT-2. _In order: micrograd → makemore 1–5 → Let's build GPT → Tokenizer → GPT-2. Code it yourself rather than just watching._
- [ ] **[Build a Large Language Model (From Scratch)](https://github.com/rasbt/LLMs-from-scratch)**  
  Sebastian Raschka · Book + repo · ~40 h · Code free, book paid  
  Build a GPT in plain PyTorch: data, attention, pretraining, classification and instruction fine-tuning, LoRA. Bonus chapters cover Llama, Qwen and Gemma. _About 106k stars and actively maintained. Pairs with Karpathy: his series for intuition, this repo for a clean reference implementation._
- [ ] **[Hugging Face LLM Course](https://huggingface.co/learn/llm-course/chapter1/1)** _(Full track: core · Builder track: optional)_  
  Hugging Face · Course · ~40 h · Free  
  The transformers, tokenizers and datasets libraries, fine-tuning with Trainer, sharing models, and the newer chapters on LLM fine-tuning and reasoning. _The best free course for working with open models. Builders can do chapters 1–4 only._

### Optional depth

- [ ] **[Generative AI and LLMs: Architecture and Data Preparation](https://www.coursera.org/learn/generative-ai-llm-architecture-data-preparation)**  
  IBM · Course · ~6 h · Audit free  
  Generative model families, tokenization, PyTorch data loaders. _Covered by the HF course._
- [ ] **[Gen AI Foundational Models for NLP](https://www.coursera.org/learn/gen-ai-foundational-models-for-nlp-and-language-understanding)**  
  IBM · Course · ~10 h · Audit free  
  N-grams, Word2Vec, seq2seq RNNs, BLEU in PyTorch. _Repeats Ng's Sequence Models._
- [ ] **[Generative AI Language Modeling with Transformers](https://www.coursera.org/learn/generative-ai-language-modeling-with-transformers)**  
  IBM · Course · ~9 h · Audit free  
  Builds attention, positional encoding, BERT- and GPT-style models in PyTorch. _Solid, but Karpathy and Raschka cover it better._
- **[Natural Language Processing Specialization](https://www.coursera.org/specializations/natural-language-processing)**  
  DeepLearning.AI · Specialization · Paid  
  Classic NLP (naive Bayes, HMMs, n-grams) through RNNs to T5/BERT, in TensorFlow. _Pre-LLM-era NLP, last updated December 2023. Not needed for AI engineering. If you want one course, take #4._
  - [ ] **[1 · Classification and Vector Spaces](https://www.coursera.org/learn/classification-vector-spaces-in-nlp)**  
    DeepLearning.AI · Course · ~33 h · Paid  
    Sentiment with logistic regression and naive Bayes, word vectors, LSH.
  - [ ] **[2 · Probabilistic Models](https://www.coursera.org/learn/probabilistic-models-in-nlp)**  
    DeepLearning.AI · Course · ~30 h · Paid  
    Autocorrect, HMM POS tagging, n-gram LMs, CBOW.
  - [ ] **[3 · Sequence Models](https://www.coursera.org/learn/sequence-models-in-nlp)**  
    DeepLearning.AI · Course · ~21 h · Paid  
    RNNs, LSTMs, GRUs, NER, Siamese nets. _Overlaps heavily with Ng's DL course 5._
  - [ ] **[4 · Attention Models](https://www.coursera.org/learn/attention-models-in-nlp)**  
    DeepLearning.AI · Course · ~26 h · Paid  
    Attention NMT, a transformer summarizer, T5/BERT question answering. _The one worth taking if you take any._
- [ ] **[LLMs from Scratch: Base Model to PPO RLHF](https://www.youtube.com/watch?v=p3sij8QzONQ)**  
  freeCodeCamp · Video · ~6 h · Free  
  Six hours of pure PyTorch: train a tiny LLM, add MoE, then SFT, reward modelling and RLHF with PPO. _Not the same as Raschka's book. Watch it after Karpathy or Raschka, because it covers the RLHF they skip._
- [ ] **[Transformers in Practice](https://www.deeplearning.ai/courses/transformers-in-practice)**  
  DeepLearning.AI × AMD · Sharon Zhou · Course · ~11 h · DLAI Pro  
  How to reason about and debug transformer behaviour, and how to make deployment decisions. _New in May 2026. Take it after Karpathy and Raschka to connect internals to engineering choices._
- [ ] **[Attention in Transformers: Concepts and Code in PyTorch](https://www.deeplearning.ai/courses/attention-in-transformers-concepts-and-code-in-pytorch)**  
  DeepLearning.AI · Josh Starmer · Short course · ~1.5 h · Free to watch  
  Derives self-attention, masked attention and multi-head attention, then codes them. _A gentle warm-up before Karpathy's 'Let's build GPT'._
- [ ] **[LLM Visualization](https://bbycroft.net/llm)**  
  Brendan Bycroft · Interactive · ~1.5 h · Free  
  A 3D walk through every step of one token's inference in a small GPT, with GPT-2 and GPT-3 scale views. _Spend an hour on it between 3Blue1Brown and Karpathy. It works on the Builder track too._
- [ ] **[Hands-On Large Language Models](https://github.com/HandsOnLLM/Hands-On-Large-Language-Models)**  
  Jay Alammar & Maarten Grootendorst · Book + notebooks · ~20 h · Notebooks free, book paid  
  A very visual book: tokens, embeddings, transformer internals, classification, clustering, semantic search and fine-tuning. _Same authors as DeepLearning.AI's How Transformer LLMs Work. Its embedding and topic-modelling chapters are the parts the route lacks._
- [ ] **[ViT and CLIP papers](https://arxiv.org/abs/2010.11929)**  
  Google · OpenAI · Papers · ~3 h · Free  
  Vision Transformer (2020) and CLIP (2021), the foundations of today's multimodal models and image embeddings. _Read them when you move into multimodal work._ Also: [CLIP paper](https://arxiv.org/abs/2103.00020)
- [ ] **[Natural Language Processing in TensorFlow](https://www.coursera.org/learn/natural-language-processing-tensorflow)**  
  DeepLearning.AI · Laurence Moroney · Course · ~23 h · Audit free  
  Tokenizing, word embeddings, LSTMs and convolutions for text, and next-word generation in TensorFlow. _Course 3 of the TensorFlow Developer certificate. Pre-transformer NLP that Ng's Sequence Models covers. Fine if you're already enrolled, but not needed._

### Reference

- [ ] **[LLM Architecture Gallery](https://sebastianraschka.com/llm-architecture-gallery/)**  
  Sebastian Raschka · Interactive reference · Free  
  Diagrams and fact sheets for about 109 current open models, with a compare tool and memory calculator. _Updated October 2026. Use it after LLMs-from-scratch to see how real models differ from your GPT._

**Build:** Train a tiny GPT on a text corpus of your choice, then load an open 1–3B model with transformers and compare their outputs.

**Move on when:** You can explain attention, KV cache, tokenization quirks and why context length costs memory.

## Stage 6: Fine-tuning and alignment _(Full track only)_

~15 h of core material (Full track).

Adapt open models with LoRA/QLoRA, instruction tuning and preference optimization (DPO), and know when fine-tuning beats prompting or RAG.

### Do these

- [ ] **[Fine-tuning & RL for LLMs: Intro to Post-training](https://www.deeplearning.ai/courses/fine-tuning-and-reinforcement-learning-for-llms-intro-to-post-training)**  
  DeepLearning.AI × AMD · Sharon Zhou · Course · ~13 h · DLAI Pro  
  SFT, RL-based alignment, reasoning improvement and evaluation of post-trained models. _The most current full post-training course on the route. The IBM fine-tuning courses are now alternatives to it._
- [ ] **[Post-training of LLMs](https://www.deeplearning.ai/courses/post-training-of-llms)**  
  DeepLearning.AI · Banghua Zhu (UW) · Short course · ~1.5 h · Free to watch  
  Hands-on SFT, DPO and online RL, and when to use each. _A short lab companion to the course above._

### Alternatives (pick at most one)

- [ ] **[Generative AI Engineering and Fine-Tuning Transformers](https://www.coursera.org/learn/generative-ai-engineering-and-fine-tuning-transformers)**  
  IBM · Course · ~8 h · Audit free  
  Fine-tuning with Hugging Face and PyTorch, then PEFT: LoRA, QLoRA, quantization. _Overlaps the HF course's fine-tuning chapters. Do one of them in depth._
- [ ] **[Generative AI Advanced Fine-Tuning for LLMs](https://www.coursera.org/learn/generative-ai-advanced-fine-tuning-for-llms)**  
  IBM · Course · ~9 h · Audit free  
  Instruction tuning, reward modelling, RLHF with PPO, DPO and the math behind it, with TRL. _Covers the same ground as DeepLearning.AI's post-training courses, with more DPO math. Pick one._

### Optional depth

- [ ] **[Reinforcement Fine-Tuning LLMs with GRPO](https://www.deeplearning.ai/courses/reinforcement-fine-tuning-llms-grpo)**  
  DeepLearning.AI × Predibase · Short course · ~2 h · Free to watch  
  Reward-function design and GRPO training for reasoning behaviour. _The RL method behind current reasoning models._

### Reference

- [ ] **[bitsandbytes installation docs](https://huggingface.co/docs/bitsandbytes/main/en/installation)**  
  Hugging Face · Docs · Free  
  The current install path is pip install bitsandbytes (Python 3.10+, PyTorch 2.4+). Prebuilt wheels cover CUDA 11.8–13, ROCm, CPU and Apple Silicon. _The old cuda_install.sh script from the original repo now returns 404._
- [ ] **[deep-learning-pytorch-huggingface](https://github.com/philschmid/deep-learning-pytorch-huggingface)**  
  Philipp Schmid · Notebook cookbook · Free  
  Notebook recipes for fine-tuning, DPO, GRPO, quantization and FSDP/DeepSpeed training on the Hugging Face stack. _Not a course, and inactive since February 2025. Most notebooks pin old TRL/PEFT versions and old models (FLAN-T5, Llama 2, Falcon). Only the 2025 ones (fine-tune LLMs in 2025, DPO in 2025, mini-R1 GRPO) are worth running, and many need A100-class GPUs._
- [ ] **[LLM Course (Labonne)](https://github.com/mlabonne/llm-course)**  
  Maxime Labonne · Roadmap + notebooks · Free  
  A roadmap in three tracks (Fundamentals, Scientist, Engineer), plus Colab notebooks for fine-tuning, quantization and model merging. _Mostly links that overlap this route. Its notebooks are good practical references for Stage 6._

**Build:** Fine-tune a small open model with QLoRA on a domain dataset, then show the improvement over the base model on a held-out eval.

**Move on when:** You can estimate the GPU memory a fine-tune needs and choose between SFT and DPO.

## Stage 7: Retrieval-augmented generation

~81 h of core material (Full track).

Ground models in your own data: chunking, embeddings, vector databases, hybrid search, reranking, query rewriting and RAG evaluation.

### Do these

- [ ] **[RAG From Scratch](https://www.youtube.com/watch?v=wd7TZ4w1mSw&list=PLfaIDFEXuae2LXbO1_PKyVJiQ23ZztA0x)**  
  LangChain · Lance Martin · Video series · ~4 h · Free  
  About 14 short videos with notebooks: indexing, multi-query, HyDE, RAG-Fusion, routing, CRAG, Self-RAG, Adaptive RAG. _From 2024, so some LangChain APIs have moved. The concepts haven't._
- [ ] **[RAG_Techniques](https://github.com/NirDiamant/RAG_Techniques)**  
  Nir Diamant · Notebooks · ~20 h · Free  
  42+ runnable notebooks, one per technique: chunking, HyDE, reranking, Graph RAG, Self-RAG/CRAG, evaluation with RAGAS and DeepEval. _About 30k stars and active. This is the RAG repo to use, and it supersedes bRAG and Advanced_RAG._
- [ ] **[Retrieval Augmented Generation (RAG)](https://www.deeplearning.ai/courses/retrieval-augmented-generation)**  
  DeepLearning.AI · Zain Hasan · Course · ~26 h · DLAI Pro  
  End-to-end RAG: retrieval, vector DBs, chunking, prompting, evaluation and production. _The structured backbone for this stage. It replaces the IBM RAG courses, which are now alternatives._
- [ ] **[Production Agentic RAG Course (arXiv Paper Curator)](https://github.com/jamwithai/production-agentic-rag-course)**  
  Jam With AI · Project course · ~30 h · Free  
  Seven weeks building one real system: FastAPI, Postgres and OpenSearch with Airflow ingestion, then BM25, hybrid search with RRF, local-LLM RAG with Ollama, Langfuse tracing, Redis caching and finally LangGraph agentic RAG with a Telegram bot. _The best capstone on the route, and it carries into Stages 8 and 9. Each week is a notebook, a Substack post and a git tag. Needs Docker and 8 GB+ RAM. Expect some setup friction, since its fixes are community-driven and its last update was April 2026. Ships no RAG eval suite, so add RAGAS yourself._
- [ ] **[Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)**  
  Anthropic · Article · ~0.5 h · Free  
  Prepend LLM-written context to each chunk before embedding and BM25. Failed retrievals drop 49%, or 67% with a reranker. _A widely cited, measured technique you can add to your Stage 7 project in an afternoon._

### Alternatives (pick at most one)

- [ ] **[Fundamentals of AI Agents Using RAG and LangChain](https://www.coursera.org/learn/fundamentals-of-ai-agents-using-rag-and-langchain)**  
  IBM · Course · ~9 h · Audit free  
  End-to-end RAG with FAISS, in-context learning, LangChain tools, chains and agents. _Some lab code lags behind current LangChain._
- [ ] **[Project: Generative AI Applications with RAG and LangChain](https://www.coursera.org/learn/project-generative-ai-applications-with-rag-and-langchain)**  
  IBM · Project course · ~10 h · Audit free  
  Capstone: build a document QA bot with loaders, splitters, embeddings, a vector DB and a Gradio UI. _The highest-rated IBM course (4.8). The Jam With AI project is now the main capstone, so this is the lighter alternative._

### Optional depth

- [ ] **[Qdrant vector DB: installation and setup](https://blog.futuresmart.ai/comprehensive-guide-to-qdrant-vector-db-installation-and-setup)**  
  FutureSmart AI · Tutorial · ~1 h · Free  
  Qdrant in Docker or in memory, collections, embeddings, filtered queries, web UI. _Check calls against the current Qdrant client, which renamed query to query_points. It's optional now because the Jam With AI project uses OpenSearch, so do this tutorial if you want Qdrant specifically._
- [ ] **[bRAG-langchain](https://github.com/bRAGAI/bRAG-langchain/)**  
  bRAGAI · Notebooks · ~8 h · Free  
  Five notebooks: multi-query, routing, RAPTOR, ColBERT, fusion and reranking. _Follows 'RAG From Scratch' closely, so it's redundant if you did that._
- [ ] **[MongoDB GenAI Showcase](https://github.com/mongodb-developer/GenAI-Showcase)**  
  MongoDB · Notebooks · Free  
  RAG and agent examples and workshops on Atlas vector search. _Only useful if MongoDB is your vector store._
- [ ] **[Advanced Retrieval for AI with Chroma](https://www.deeplearning.ai/courses/advanced-retrieval-for-ai)**  
  DeepLearning.AI × Chroma · Short course · ~1 h · Free to watch  
  Query expansion, cross-encoder reranking and embedding adapters. _The techniques carry over to any vector store._
- [ ] **[Document AI: From OCR to Agentic Doc Extraction](https://www.deeplearning.ai/courses/document-ai-from-ocr-to-agentic-doc-extraction)**  
  DeepLearning.AI · Short course · Free to watch  
  Agentic parsing of documents grounded in their visual parts: charts, tables and forms. _From January 2026. Covers Ng's 'document transformation pipelines', which none of the RAG courses go deep on._
- [ ] **[Knowledge Graphs for RAG](https://www.deeplearning.ai/courses/knowledge-graphs-rag)**  
  DeepLearning.AI × Neo4j · Short course · Free to watch  
  Build a knowledge graph and query it with Cypher to improve retrieval. _From 2024 and tied to Neo4j, but it's the only hands-on intro to Ng's 'knowledge graphs' representation choice on the route._
- [ ] **[GraphRAG](https://github.com/microsoft/graphrag)**  
  Microsoft Research · Library · Free  
  Builds a knowledge graph and community summaries from your documents with an LLM, then answers global and local questions over them. _The reference implementation of graph RAG. It's now in maintenance mode, and indexing is expensive, so try it on a small corpus first._

### Reference

- [ ] **[Emerging LLM App Stack](https://github.com/a16z-infra/llm-app-stack)**  
  a16z · Link list · ~1 h · Free  
  Tools listed by layer: data pipelines, embeddings, vector DBs, orchestration, eval, hosting. _A good mental model, but the tool lists stopped in February 2024 and predate agents and MCP. The companion article has the architecture diagram._ Also: [Companion article](https://a16z.com/emerging-architectures-for-llm-applications/)
- [ ] **[Vector Database Comparison](https://superlinked.com/vector-db-comparison)**  
  Superlinked · Comparison table · Free  
  About 47 vector DBs compared on features, pricing, performance and integrations. _Maintained (August 2026). Use it when picking a store beyond Qdrant or OpenSearch._
- [ ] **[sentence-transformers](https://github.com/huggingface/sentence-transformers)**  
  Hugging Face · Library · Free  
  The standard library for local embedding, retrieval and reranking models, and for fine-tuning them. _Moved from UKPLab to Hugging Face. Docs are at sbert.net. Read them as needed._

**Build:** Build a question-answering bot over your own docs (for example, a codebase you know well) using Qdrant, with an evaluation set scored by RAGAS or similar.

**Move on when:** You can show measured retrieval precision before and after a reranker.

## Stage 8: Agents

~89 h of core material (Full track).

Build tool-using and multi-step agents: the ReAct loop, LangGraph state machines, MCP servers and multi-agent patterns, plus knowing when not to use an agent.

### Do these

- [ ] **[Hugging Face AI Agents Course](https://huggingface.co/learn/agents-course/unit0/introduction)**  
  Hugging Face · Course · ~16 h · Free + free cert  
  Thought-action-observation, tools, smolagents, LangGraph, LlamaIndex, agentic RAG, and a benchmarked final project. _The free core path for agents._
- [ ] **[GenAI_Agents](https://github.com/NirDiamant/GenAI_Agents)**  
  Nir Diamant · Notebooks · ~20 h · Free  
  About 57 agent tutorials, mostly LangGraph, plus CrewAI, AutoGen, PydanticAI and MCP. _Start with the beginner and framework section. The use-case demos vary in depth._
- [ ] **[Agentic AI](https://www.deeplearning.ai/courses/agentic-ai)**  
  DeepLearning.AI · Andrew Ng · Course · ~10 h · DLAI Pro  
  Agent workflows in plain Python: reflection, tool use, planning, multi-agent patterns, error analysis and evals. _Framework-agnostic, so take it first in this stage, before LangGraph._
- [ ] **[MCP: Build Rich-Context AI Apps with Anthropic](https://www.deeplearning.ai/courses/mcp-build-rich-context-ai-apps-with-anthropic)**  
  DeepLearning.AI × Anthropic · Short course · ~2 h · Free to watch  
  Build MCP servers and clients, connect them to Claude Desktop, and deploy a remote server. _Needed for the Stage 8 project._
- [ ] **[CMU 11-768: AI Agents (Fall 2026)](https://www.cmu-agents.com/#/schedule)** _(Full track: core · Builder track: optional)_  
  CMU · Graham Neubig & Daniel Fried · University course · ~40 h · Free materials  
  Build an agent harness from scratch on an open model, design multi-step evals, and train agents with SFT and RL. _The only item on the route that covers agent harness internals and RL for agents. The course is running now, so slides and videos are still being released. It's graduate level, so take it last in this stage._
- [ ] **[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)**  
  Anthropic · Erik Schluntz & Barry Zhang · Article · ~0.5 h · Free  
  Workflow patterns first (prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer), then autonomous agents, with the advice to stay simple and skip frameworks until needed. _Matches Ng's 'architecture selection' skill exactly. Read it before picking LangGraph or CrewAI._
- [ ] **[Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)**  
  Anthropic · Article · ~0.5 h · Free  
  Treat context as a scarce budget: right-altitude system prompts, token-efficient tools, just-in-time retrieval, compaction, structured notes and sub-agents. _Ng lists context management under both agentic systems and coding agents. This is the clearest single source._
- [ ] **[The Lethal Trifecta for AI Agents](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)**  
  Simon Willison · Article · ~0.3 h · Free  
  An agent with private data, exposure to untrusted content and a way to communicate externally can be made to leak that data through prompt injection, and guardrails don't reliably stop it. _The mental model for Ng's 'guardrails and adversarial input' skill. Design your Stage 8 agent so it never has all three._

### Alternatives (pick at most one)

- [ ] **[IBM RAG and Agentic AI Professional Certificate](https://www.coursera.org/professional-certificates/ibm-rag-and-agentic-ai)**  
  IBM · Certificate · ~40 h · Audit free  
  Ten courses: LangChain, RAG with Chroma and FAISS, LangGraph, CrewAI, AG2, BeeAI, MCP, multimodal, capstone. _The structured, credentialed alternative to the HF course plus GenAI_Agents, and it's current (includes MCP)._
- [ ] **[The AI Engineer Path](https://v2.scrimba.com/the-ai-engineer-path-c02v)**  
  Scrimba · Course path · ~17 h · Paid (Scrimba Pro)  
  For JavaScript developers: LLM APIs, RAG, agents, MCP, multimodal, deployment on Cloudflare. _Pick this only if you'd rather build AI apps in JS than Python. It includes your two other Scrimba links._

### Optional depth

- [ ] **[Shandu](https://github.com/jolovicdev/shandu)**  
  jolovicdev · Open-source tool · Free  
  A deep-research agent (CLI + Gradio) that searches, scores sources and writes cited reports. _Read its ARCH.md as a reference architecture after you've built your own agent._
- [ ] **[AI Agents in LangGraph](https://www.deeplearning.ai/courses/ai-agents-in-langgraph)**  
  DeepLearning.AI × LangChain · Short course · ~2 h · Free to watch  
  An agent built from scratch and then in LangGraph, covering state, persistence and human-in-the-loop. _From 2024, so check the code against current LangGraph._
- [ ] **[Agent Memory: Building Memory-Aware Agents](https://www.deeplearning.ai/courses/agent-memory-building-memory-aware-agents)**  
  DeepLearning.AI × Oracle · Short course · ~2 h · Free to watch  
  Memory that lets an agent store, retrieve and refine knowledge across sessions. _From 2026. It supersedes the older Letta and LangGraph memory courses._
- [ ] **[Agent Skills with Anthropic](https://www.deeplearning.ai/courses/agent-skills-with-anthropic)**  
  DeepLearning.AI × Anthropic · Short course · ~2 h · Free to watch  
  Package on-demand expertise as Skills for coding, research and data agents. _Context engineering through progressive disclosure. It pairs with MCP._
- [ ] **[Multi-Agent Systems with CrewAI](https://www.deeplearning.ai/courses/design-develop-and-deploy-multi-agent-systems-with-crewai)**  
  DeepLearning.AI × CrewAI · Course · ~13 h · DLAI Pro  
  Multi-agent systems with tools, memory, guardrails and deployment. _Tied to CrewAI. Take it only if multi-agent work is your focus._
- [ ] **[A2A: The Agent2Agent Protocol](https://www.deeplearning.ai/courses/a2a-the-agent2agent-protocol)**  
  DeepLearning.AI × Google Cloud & IBM · Short course · ~1.5 h · Free to watch  
  Make agents built on different frameworks interoperate. _MCP connects agents to tools, and A2A connects agents to each other._
- [ ] **[Gemini Fullstack LangGraph Quickstart](https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart)**  
  Google Gemini · Template · ~3 h · Free (API key)  
  React frontend plus LangGraph backend for a research agent that searches, reflects and cites. _A clean full-stack template for your Stage 8 project. Swap Gemini for any model._
- [ ] **[AI Agents for Beginners](https://github.com/microsoft/ai-agents-for-beginners)**  
  Microsoft · Course (18 lessons) · ~15 h · Free  
  Agent design patterns, MCP and A2A, context engineering, memory and agent security, on the Microsoft Agent Framework. _Mostly overlaps the HF Agents course. Its context-engineering and memory lessons are the useful extra. Translations, including Bulgarian, are in the repo's translations folder._
- [ ] **[ollama-playground](https://github.com/NarimanN2/ollama-playground)**  
  Nariman N. · Projects · Free  
  Small local-model projects: PDF and hybrid RAG, MCP agents, multi-agent supervisor and swarm, voice, vision. _Project ideas that run entirely on your machine._
- [ ] **[Building Coding Agents with Tool Execution](https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution)**  
  DeepLearning.AI · Short course · Free to watch  
  Agents that write and run code in sandboxed cloud environments. _Covers Ng's 'code versus LLM execution' and 'sandbox environments'._
- [ ] **[text2sql-framework](https://github.com/Text2SqlAgent/text2sql-framework)**  
  Text2SqlAgent · Library · Free  
  An agent with a single execute_sql tool that explores the schema, tests queries and corrects itself, with no RAG or semantic layer. It also ships as an MCP server. _A small, readable case study in giving an agent one good tool. Its benchmark is self-reported on 20 questions._
- [ ] **[Deep Agents](https://github.com/langchain-ai/deepagents)**  
  LangChain · Agent harness · Free (MIT)  
  A batteries-included agent harness (Python and TypeScript) with planning, sub-agents with isolated context, a pluggable filesystem, context summarization, sandboxed shell, persistent memory, human-in-the-loop, skills and MCP tools. _The 'deep agent' pattern behind coding agents like Claude Code, packaged so you can build your own. About 30k stars and very active. Read Building Effective Agents first so you know when you need this much harness._ Also: [Docs](https://docs.langchain.com/oss/python/deepagents/overview)
- [ ] **[Introduction to Deep Agents](https://academy.langchain.com/courses/foundation-introduction-to-deepagents)**  
  LangChain Academy · Course · Free  
  LangChain's free course on building long-running agents with planning, sub-agents and a filesystem using the Deep Agents library. _Take it with the Deep Agents repo open._

### Reference

- [ ] **[Awesome LLM Apps](https://github.com/Shubhamsaboo/awesome-llm-apps)**  
  Shubham Saboo · Example apps · Free  
  100+ small runnable apps: starter and advanced agents, multi-agent teams, voice and MCP agents, RAG and memory apps. _Demo quality, not production patterns. Use it for project ideas, and GenAI_Agents for how things work._
- [ ] **[Awesome LangGraph](https://github.com/vonzosten/awesome-LangGraph)**  
  vonzosten · Link list · Free  
  Index of the LangChain and LangGraph ecosystem: concepts, templates, tools, UIs and tutorials. _Only useful once you've chosen LangGraph._

**Build:** Build a research agent with web search, a code tool and an MCP server you wrote, and add traces you can inspect.

**Move on when:** You can explain why your agent failed on a task by reading its trace, and say which leg of the lethal trifecta you removed from it.

## Stage 9: Production: MLOps and LLMOps

~100 h of core material (Full track).

Deploy, monitor and iterate: experiment tracking, model registry, orchestration, CI/CD, observability, guardrails, cost and latency.

### Do these

- [ ] **[Machine Learning in Production](https://www.coursera.org/learn/introduction-to-machine-learning-in-production/)**  
  DeepLearning.AI · Andrew Ng · Course · ~12 h · Paid  
  The ML project lifecycle: scoping, deployment patterns, drift, error analysis, data-centric AI. _Conceptual. Take it before MLOps Zoomcamp._
- [ ] **[MLOps Zoomcamp](https://github.com/DataTalksClub/mlops-zoomcamp)**  
  DataTalks.Club · Course · ~60 h · Free  
  MLflow tracking and registry, Prefect orchestration, batch, web and stream deployment, Evidently, Grafana monitoring, CI/CD, Terraform. _No 2026 cohort, so it's self-paced. Covers MLflow. Kubeflow isn't covered anywhere on the map._
- [ ] **[Agents Towards Production](https://github.com/NirDiamant/agents-towards-production)**  
  Nir Diamant · Notebooks · ~25 h · Free  
  Taking agents to production: memory, tool auth, guardrails, tracing, evaluation, Docker/GPU deployment. _Many tutorials are sponsored, so the stacks are vendor-specific. Learn the pattern and swap in the vendor you prefer._
- [ ] **[Evaluating AI Agents](https://www.deeplearning.ai/courses/evaluating-ai-agents)**  
  DeepLearning.AI × Arize · Short course · ~3 h · Free to watch  
  Tracing, component and trajectory evals, LLM-as-judge, and experiment-driven iteration. _The best evals course in the catalogue. Its ideas apply from Stage 2 onward._

### Alternatives (pick at most one)

- [ ] **[LLM Engineer's Handbook](https://github.com/PacktPublishing/LLM-Engineers-Handbook)**  
  Paul Iusztin & Maxime Labonne · Packt · Book + project · Code free, book paid  
  Builds one end-to-end 'LLM Twin': crawling, feature pipelines, Qdrant RAG, SFT and DPO finetuning, and AWS SageMaker deployment with LLMOps. _The most complete feature/training/inference pipeline example. The code is frozen at 2024 tooling (Poetry, ZenML, Llama 3.1), so expect setup work. Pick it over the Jam With AI project if you want finetuning and AWS._

### Optional depth

- [ ] **[Machine Learning Zoomcamp](https://github.com/DataTalksClub/machine-learning-zoomcamp)**  
  DataTalks.Club · Alexey Grigorev · Course · ~120 h · Free  
  Project-based ML engineering: sklearn, FastAPI + Docker deployment, trees, DL, serverless, Kubernetes. _Core if you want a classic ML-engineer job. The 2026 cohort started on 14 September and you can join late._
- [ ] **[Apache Airflow](https://github.com/apache/airflow)**  
  Apache · Framework · Free  
  Workflow orchestration with Python DAGs. Airflow 3.x is current. _Learn it from the official tutorial, not the repo. Only needed for data and ML pipeline work._
- [ ] **[DeepLearning.AI Data Engineering Professional Certificate](https://www.coursera.org/professional-certificates/data-engineering)**  
  DeepLearning.AI & AWS · Joe Reis · Certificate · ~106 h · Paid  
  Pipelines on AWS: ingestion, storage, modelling, Airflow, Spark, SQL, IaC. _An adjacent skill, not AI, and a good way to learn SQL properly._
- [ ] **[Foundations of AI and Machine Learning](https://www.coursera.org/learn/foundations-of-ai-and-machine-learning)**  
  Microsoft · Course · ~40 h · Audit free  
  AI/ML infrastructure: data pipelines, frameworks, deployment, versioning, on Azure. _Course 1 of the Microsoft AI & ML cert. Despite the title, it's about infrastructure._
- [ ] **[NeMo Agent Toolkit: Making Agents Reliable](https://www.deeplearning.ai/courses/nvidia-nat-making-agents-reliable)**  
  DeepLearning.AI × Nvidia · Short course · ~1.5 h · Free to watch  
  Observability, evaluation and deployment tooling for agents moving from prototype to production. _Tied to Nvidia, but the concepts carry over._
- [ ] **[Safe and Reliable AI via Guardrails](https://www.deeplearning.ai/courses/safe-and-reliable-ai-via-guardrails)**  
  DeepLearning.AI × GuardrailsAI · Short course · ~2 h · Free to watch  
  Input and output validators against hallucination, PII leaks and off-topic answers. _The only guardrails-focused course in the catalogue._
- [ ] **[Fast & Efficient LLM Inference with vLLM](https://www.deeplearning.ai/courses/fast-and-efficient-llm-inference-with-vllm)**  
  DeepLearning.AI × Red Hat · Short course · ~1.5 h · Free to watch  
  Optimize, deploy and benchmark an open model with vLLM. _For when you self-host the models you fine-tuned in Stage 6._
- [ ] **[Semantic Caching for AI Agents](https://www.deeplearning.ai/courses/semantic-caching-for-ai-agents)**  
  DeepLearning.AI × Redis · Short course · ~1.5 h · Free to watch  
  Cut latency and cost by caching responses by meaning. _A practical cost lever that nothing else on the route covers._
- [ ] **[From MLOps to ML Systems with FTI Pipelines](https://www.hopsworks.ai/post/mlops-to-ml-systems-with-fti-pipelines)**  
  Hopsworks · Jim Dowling · Article · ~0.5 h · Free  
  Split any ML system into feature, training and inference pipelines, a simple mental model for architecture. _Read it alongside MLOps Zoomcamp._
- [ ] **[What is Inference?](https://theaiengineer.substack.com/p/what-is-inference)**  
  Paolo Perrone · The AI Engineer · Article · ~0.3 h · Free  
  Prefill versus decode, the KV cache, why output tokens cost more, and PagedAttention. _From August 2026. A good primer before the vLLM course._
- [ ] **[Made With ML](https://github.com/GokuMohandas/Made-With-ML)**  
  Goku Mohandas · Course · ~30 h · Free  
  Take a PyTorch model to production with Ray, MLflow, pytest and GitHub Actions CI/CD. _Overlaps MLOps Zoomcamp. Its extras are Ray-based scaling and stronger software-engineering discipline._
- [ ] **[Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)**  
  Google Cloud · Templates · Free (GCP billed)  
  Production agent templates with CI/CD, evaluation and observability built in. _Only if you deploy on GCP. It used to live in Google's generative-ai repo._
- [ ] **[Red Teaming LLM Applications](https://www.deeplearning.ai/courses/red-teaming-llm-applications)**  
  DeepLearning.AI × Giskard · Short course · Free to watch  
  Find and evaluate vulnerabilities in LLM apps: prompt injection, data leaks, harmful outputs. _From 2024. Pair it with the lethal-trifecta article for Ng's 'security incident management'._
- [ ] **[Governing AI Agents](https://www.deeplearning.ai/courses/governing-ai-agents)**  
  DeepLearning.AI · Short course · Free to watch  
  Build data governance into an agent's workflow so it handles data safely, securely and accurately. _Covers Ng's 'privacy, governance and compliance' item._
- [ ] **[LangSmith Agent Lifecycle Workshop](https://github.com/langchain-ai/langsmith-agent-lifecycle-workshop)**  
  LangChain · Workshop · Free  
  Build a support agent in LangGraph, improve it with offline evals, then deploy it with online evals and a CI eval that blocks regressions. _A compact build-evaluate-deploy loop that bridges Stages 8 and 9. Worth it if LangGraph and LangSmith are your stack._
- [ ] **[LangSmith](https://www.langchain.com/langsmith)**  
  LangChain · Platform · Free tier  
  Tracing, monitoring dashboards, online LLM-as-judge and code evals, trajectory monitoring, failure clustering and deployment for agents. _Works with any framework (OpenAI and Anthropic SDKs, LlamaIndex, Vercel AI SDK), not only LangChain. Langfuse, used in the Jam With AI project, is the open-source alternative. Pick one for your Stage 9 project._ Also: [Observability docs](https://docs.langchain.com/langsmith/observability)
- [ ] **[Quickstart: LangSmith Essentials](https://academy.langchain.com/courses/quickstart-langsmith-essentials)**  
  LangChain Academy · Course · Free  
  A quick, free introduction to tracing, datasets and evaluations in LangSmith. _Pairs with the LangSmith Agent Lifecycle Workshop above. Academy also has a free LangSmith Deployment course._ Also: [Introduction to LangSmith Deployment](https://academy.langchain.com/courses/langsmith-deployment)

### Reference

- [ ] **[ml-ops.org](https://ml-ops.org/)**  
  INNOQ · Docs · Free  
  MLOps principles, maturity levels, CRISP-ML(Q), testing and governance. _Conceptual, tool-agnostic, and older than LLMOps._

**Build:** Ship your Stage 7 or Stage 8 app with Docker, run its eval suite in CI, add tracing, monitoring and drift alerts, and write a cost-per-request report with one lever you pulled (cheaper model, caching or a simpler workflow).

**Move on when:** A regression in your prompt or model gets caught by CI before users see it.

## Alongside every stage

Andrew Ng's AI Engineering Skills Map has four pillars. The stages above cover the first one, building and deploying AI apps. These three tracks cover the rest. Work on them alongside the stages, not after.

### Track A: Using coding agents

~2 h of core material (Full track).

Ng's third pillar. Plan, then let agents execute, then verify. The skill is directing that loop: how much autonomy to give, how to manage context, and how to review what comes back. If you already customize your agent setup, focus on spec-first planning and on reviewing what comes back.

#### Do these

- [ ] **[Claude Code: A Highly Agentic Coding Assistant](https://www.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant)**  
  DeepLearning.AI × Anthropic · Short course · ~2 h · Free to watch  
  Subagents, hooks, MCP and GitHub integration in a real agent harness. _Ng's 'customizing agent and environment' skills. If you already run a customized agent setup, skim for what you haven't set up._
- [ ] **[Spec-Driven Development with Coding Agents](https://www.deeplearning.ai/courses/spec-driven-development-with-coding-agents)**  
  DeepLearning.AI · Short course · Free to watch  
  Write specs that give a coding agent the context to build intentional, maintainable software instead of vibe-coding. _From April 2026. It's Ng's 'planning' phase, the part most people skip._
- [ ] **[Agent Skills (Anthropic)](https://github.com/anthropics/skills)**  
  Anthropic · Spec + examples · Free  
  The SKILL.md format spec, a template, and example skills, including the document skills and a Claude API skill. _Read the spec and template before any third-party skill pack. They all build on this format._
- [ ] **[agent-skills](https://github.com/addyosmani/agent-skills)**  
  Addy Osmani · Skill pack · Free  
  25 engineering skills and 9 commands (/spec, /plan, /build, /test, /review, /ship) that encode a define-plan-build-verify-review-ship workflow for Claude Code, Codex, Gemini and others. _Spec-driven development you can install and take apart, and it has its own evals. Pair it with the Spec-Driven Development course._

#### Alternatives (pick at most one)

- [ ] **[gstack](https://github.com/garrytan/gstack)**  
  Garry Tan · Claude Code setup · Free  
  About 23 role-based slash commands (plan review, engineering manager, designer, QA with a real browser, security audit, ship and deploy) built as Markdown skills. _An example of a full role-based harness. It's opinionated and complex. Study it for ideas, and use agent-skills as the cleaner base._

#### Optional depth

- **[Generative AI for Software Development](https://www.coursera.org/professional-certificates/generative-ai-for-software-development)**  
  DeepLearning.AI · Laurence Moroney · Certificate · Audit free  
  Using LLMs as a pair programmer: writing, testing, documenting code and AI-assisted design. _About productivity, not about building AI. It's from before agentic coding tools, so it teaches chat-based pair programming. Its three courses are listed below._
  - [ ] **[1 · Introduction to Generative AI for Software Development](https://www.coursera.org/learn/introduction-to-generative-ai-for-software-development)**  
    DeepLearning.AI · Laurence Moroney · Course · ~9 h · Audit free  
    How LLMs work for code, prompting an LLM as a pair programmer, and using it to write, refactor and debug code.
  - [ ] **[2 · Team Software Engineering with AI](https://www.coursera.org/learn/team-software-engineering-with-ai)**  
    DeepLearning.AI · Laurence Moroney · Course · ~13 h · Audit free  
    Using LLMs for testing, debugging, documentation and dependency management. _Closest to Ng's 'reviewing the work' skill._
  - [ ] **[3 · AI-Powered Software and System Design](https://www.coursera.org/learn/ai-powered-software-and-system-design)**  
    DeepLearning.AI · Laurence Moroney · Course · ~12 h · Audit free  
    Using LLMs for software design: data serialization and storage choices, database design, and design patterns. _Also counts toward Track B, since it covers design tradeoffs._

**Build:** Pick one feature of your portfolio project. Write the spec and an execution plan first, let an agent build it in a worktree, then review it against tests you wrote before seeing its code.

**Move on when:** You can name Ng's four agent failure modes (overengineering, lost rigour, stopping too early, destructive actions) and show the guard you use for each.

### Track B: Software engineering fundamentals

~2 h of core material (Full track).

Ng's second pillar: full-stack apps, data management, architecture, security and reliability, and running in production. Agents write the code, but you still choose the tradeoffs. If you have backend or infrastructure experience, much of it will be familiar, so use Part 3 as a checklist and only study the gaps.

#### Do these

- [ ] **[Skills Map Part 3: Software Engineering Fundamentals](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map-in-detail-software-engineering-fundamentals)**  
  Andrew Ng · The Batch · Article (checklist) · ~0.3 h · Free  
  Five areas: full-stack apps, managing data, system architecture, security and reliability, scaling and operating in production. _Read it as a checklist and mark what you already know._
- [ ] **[Designing Data-Intensive Applications (2nd edition)](https://martin.kleppmann.com/2026/03/24/designing-data-intensive-applications-2e.html)**  
  Martin Kleppmann & Chris Riccomini · O'Reilly · Book · Paid  
  How data systems really work: data models, storage engines, replication, partitioning, transactions, consistency, batch and stream processing. _The 2nd edition came out in 2026. It's the deepest single read for Ng's 'managing data' and 'designing system architectures'. The linked repo has up-to-date links for every reference in the book._ Also: [References repo](https://github.com/ept/ddia2-references)
- [ ] **[FastAPI Best Practices](https://github.com/zhanymkanov/fastapi-best-practices)**  
  zhanymkanov · Guide · ~2 h · Free  
  Production FastAPI conventions: project structure, async versus sync routes, Pydantic models, dependencies, background tasks versus queues, migrations and testing. _Most AI backends on this map are FastAPI, including the Jam With AI project. It also ships an AGENTS.md, so your coding agent can follow the same rules._

#### Alternatives (pick at most one)

- [ ] **[Algorithms for Searching, Sorting, and Indexing](https://www.coursera.org/learn/algorithms-searching-sorting-indexing)**  
  CU Boulder · Sriram Sankaranarayanan · Course · ~36 h · Coursera Plus  
  Sorting and searching with proofs and Big-O, heaps and priority queues, randomized quicksort, and hashing up to Bloom filters and count-min sketches, in Python. _Part of CU Boulder's data structures and algorithms specialization. It overlaps Princeton's Part I but is in Python, adds Bloom filters and count-min sketches, and the certificate needs Coursera Plus. Pick one._
- [ ] **[System Design (Karan Pratap Singh)](https://github.com/karanpratapsingh/system-design)**  
  Karan Pratap Singh · Guide · Free  
  One linear guide from networking and DNS through databases, caching, CAP and PACELC, messaging, microservices and rate limiting to worked designs. _Covers the same ground as the System Design Primer but reads more like a course. Pick one._

#### Optional depth

- [ ] **[Algorithms, Part I](https://www.coursera.org/learn/algorithms-part1)**  
  Princeton · Sedgewick & Wayne · Course · ~50 h · Free  
  Union-find, analysis of algorithms, stacks and queues, the sorts, priority queues, symbol tables, balanced search trees and hash tables. _Free, rated 4.9 from 12k reviews, and the classic. Programming assignments are in Java. Do it if your CS theory is rusty._
- [ ] **[Algorithms, Part II](https://www.coursera.org/learn/algorithms-part2)**  
  Princeton · Sedgewick & Wayne · Course · ~60 h · Free  
  Graphs, shortest paths, max flow, radix sorts, tries, substring search, regular expressions, compression, reductions and intractability. _Graphs and tries come up again in knowledge-graph RAG and tokenizers. Optional even within this track._
- [ ] **[TOGAF 10 Foundation](https://www.coursera.org/learn/togaf-10-foundation)**  
  EDUCBA · Course · ~7 h · Coursera Plus  
  The TOGAF enterprise-architecture framework: BDAT domains, the ADM phases A to H, requirements management, architecture principles, governance and stakeholder management. _Not AI, but it's the shared language for architecture work in larger organizations, and it fits Ng's 'designing system architectures' and 'aligning stakeholders' skills. The publisher mass-produces courses, so treat this as a primer and use The Open Group's TOGAF Standard as the source if you go for the certification._
- [ ] **[Build Your Own X](https://github.com/codecrafters-io/build-your-own-x)**  
  CodeCrafters · Tutorial index · Free  
  Tutorials for building your own database, Redis, Git, Docker, shell, web server or neural network from scratch, in many languages. _The best way to really understand a tool is to rebuild it. Pick one project that matches a gap from the Part 3 checklist._

#### Reference

- [ ] **[System Design Primer](https://github.com/donnemartin/system-design-primer)**  
  Donne Martin · Guide · Free  
  Scalability, CAP, caching, load balancing, SQL vs NoSQL, async and queues, with worked design cases. _About 373k stars. Use it only for the checklist items you're unsure of._
- [ ] **[System Design 101](https://github.com/ByteByteGoHq/system-design-101)**  
  ByteByteGo · Visual cheat sheets · Free  
  Short visual explainers on APIs, databases, caching, microservices, cloud, DevOps and security. _Good for quick review. The content now lives on bytebytego.com, and the repo is its index._
- [ ] **[Data Engineer Handbook](https://github.com/DataExpert-io/data-engineer-handbook)**  
  DataExpert.io · Zach Wilson · Link hub + bootcamp · Free  
  Books, courses, company blogs, newsletters and free beginner and intermediate bootcamp materials for data engineering. _Partly promotional. Use the books list and bootcamp folders if data pipelines are your gap._

**Build:** Score yourself against the five areas in Part 3. For each weak item, write a one-paragraph design note on how your Stage 7 or Stage 8 project handles it.

**Move on when:** You can defend your project's data store, sync versus async processing, and deployment choices in terms of latency, cost and reliability.

### Track C: Shaping the build

~0 h of core material (Full track).

Ng's fourth pillar: deciding what to build, not just how. This means product sense, business basics, explaining feasibility to non-engineers, and owning outcomes. It's learned by doing, so this track is mostly a way of running your projects.

#### Do these

- [ ] **[Skills Map Part 5: Shaping the Build](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map-in-detail-shaping-the-build)**  
  Andrew Ng · The Batch · Article (checklist) · ~0.3 h · Free  
  Driving the build loop, making product decisions, communicating and leading, and high-agency ownership. _Nothing else on the route teaches this, and it's mostly practice. The track's project is where you learn it._

#### Optional depth

- [ ] **[Systems Engineering](https://www.coursera.org/learn/systems-engineering-mathworks)**  
  MathWorks · Course · ~1.5 h · Coursera Plus  
  Five short videos on requirements, functional architectures, trade studies and model-based systems engineering. _A 90-minute primer on turning needs into requirements and making tradeoffs explicit, which is the core of Ng's 'shaping the build'. It also supports writing specs for coding agents (Track A)._

**Build:** For your capstone, talk to 2–3 potential users before building, pick one metric that shows value, ship in small batches, and write a one-page update for a non-technical reader.

**Move on when:** You can explain your project's user, its metric and its cost per request to someone outside engineering in two minutes.

## Reference shelf

- [ ] **[AI Engineering From Scratch](https://github.com/rohitg00/ai-engineering-from-scratch)**  
  Rohit Ghumare · Curriculum · ~342 h · Free (MIT)  
  523 text-and-code lessons in 20 phases, from math to agents, MCP, production and safety. It's very current (2026) and updated daily. _Its phases map onto this route (P1→Stage 1, P2→3, P3→4, P7/P10→5, P10/P11→6, P11→7, P13–16→8, P17→9), but don't follow all 342 hours. It grew very fast and looks heavily AI-assisted, so quality varies by lesson. Use it to fill gaps (Agent Skills, coding agents, 2026 architectures) and as a second explanation, not as a replacement for Karpathy or Raschka._
- [ ] **[Become a Machine Learning Engineer](https://www.maxmynter.com/pages/blog/become-mle)**  
  Max Mynter · Roadmap post · Free  
  A second-opinion roadmap for software engineers, which recommends mostly the same resources as this route. _Reassurance that the route is sensible, and nothing more._
- [ ] **[Hugging Face Papers (formerly Papers with Code)](https://huggingface.co/papers/trending)**  
  Hugging Face · Paper feed · Free  
  Trending research papers with code links. _paperswithcode.com now redirects here._
- [ ] **[The curator's GitHub stars](https://github.com/stanimirdim92?tab=stars)**  
  stanimirdim92 · GitHub stars · Free  
  Repos the map's curator follows: AI engineering courses and books, agent skills and harnesses, system design, Python and infrastructure lists. _About 20 of these 87 are placed in stages and tracks on this map. The rest are developer tools and lists outside its scope._
- [ ] **[learn-ai-engineering](https://github.com/ashishps1/learn-ai-engineering)**  
  Ashish Pratap Singh · Link list · Free  
  A curated list of free resources across math, ML, DL, LLMs, RAG, agents and MLOps. _Already includes many items on this route. Use it to find a second explanation for a topic._
- [ ] **[AI Engineer Roadmap](https://roadmap.sh/ai-engineer)**  
  roadmap.sh · Roadmap · Free  
  An interactive topic map for applied AI engineers, with links per node. _Use it as a checklist against this route._
- [ ] **[The AI Engineer's Handbook](https://handbook.exemplar.dev/)**  
  Exemplar · Handbook · Free  
  A survey of prompting, vector DBs, RAG, agents, evaluation and security. _No date and an unknown author. Use it for lookups only._
- [ ] **[best-of-ml-python](https://github.com/ml-tooling/best-of-ml-python)**  
  ml-tooling · Link list · Free  
  Ranked ML Python libraries by category. _Use it to compare libraries. Updates have slowed since March 2026._
- [ ] **[LF AI & Data Landscape](https://landscape.lfai.foundation/)**  
  Linux Foundation · Ecosystem map · Free  
  A map of open-source AI and data projects. _Useful for getting oriented, not for learning._
- [ ] **[How I started learning ML](https://www.reddit.com/r/learnmachinelearning/comments/1g4x299/how_i_started_learning_machine_learning/)**  
  r/learnmachinelearning · Forum post · Free  
  One person's path: CS229, Ng, Goodfellow, Kaggle, FastAPI, HF, Unsloth, LangGraph. _Low engagement, self-promotional, and some links are dated. This route already covers it._
- [ ] **[What is an AI engineer?](https://www.coursera.org/articles/ai-engineer)**  
  Coursera · Career article · Free  
  The role, skills and salary (about $138k median in the US). _Mostly marketing for Coursera programs._

## What to follow

### Learning platforms

Where the structured courses live.

- **[DeepLearning.AI](https://www.deeplearning.ai/)**  
  Andrew Ng · Learning platform · Freemium  
  Andrew Ng's platform: short courses with OpenAI, Anthropic, Google, Hugging Face and others, longer programs such as Agentic AI and RAG, and The Batch newsletter. _About 25 of its 131 courses are placed on this map. Short courses are free to watch, and longer ones need DeepLearning.AI Pro._
- **[Hugging Face Learn](https://huggingface.co/learn)**  
  Hugging Face · Learning platform · Free  
  Twelve free courses: LLMs, agents, context engineering, deep RL, computer vision, audio, diffusion, robotics, games and 3D, plus the Open-Source AI Cookbook. _The LLM and Agents courses are on the map (Stages 5 and 8). The others are worth knowing when you branch out._
- **[LangChain Academy](https://academy.langchain.com/)**  
  LangChain · Learning platform · Free (paid certification)  
  Free courses on LangChain, LangGraph, Deep Agents and LangSmith, grouped as Build, Test, Deploy and Monitor. _All course content is free. Only the Certified Agent Engineer exam is paid._
- [ ] **[Kaggle Learn](https://www.kaggle.com/learn)**  
  Kaggle · Micro-courses · ~8 h · Free  
  In-browser 3–5 hour courses: pandas, data cleaning, feature engineering, data viz, plus Google's self-paced GenAI and Agents intensives. _Do the pandas and feature-engineering ones before Stage 3. The ML and agent ones repeat what's on the route._
- [ ] **[DeepLearning.AI Learning Platform (My Learnings)](https://learn.deeplearning.ai/my/learnings)**  
  DeepLearning.AI + partners · Course platform · ~8 h · Freemium  
  1–2 hour hands-on courses on prompting, RAG, agents, evals and fine-tuning, made with OpenAI, Anthropic, LangChain, Hugging Face and others. _Your own dashboard of courses in progress once you're signed in. The full catalogue has 131 items. The 25 worth taking are placed in their stages on this map, and the rest are mostly thin partner showcases or superseded 2023–24 courses. Short courses are free to watch, while the longer courses and certificates need DeepLearning.AI Pro._ Also: [Course catalogue](https://www.deeplearning.ai/courses/)

### News and digests

Skim weekly to stay oriented.

- **[The Batch](https://www.deeplearning.ai/the-batch/)**  
  DeepLearning.AI · Andrew Ng · Newsletter · Free  
  Weekly AI news with Andrew Ng's letter, where the AI Engineering Skills Map series ran. _A low-effort weekly way to stay oriented._
- **[Latent Space](https://www.latent.space/)**  
  swyx & Alessio Fanelli · Newsletter + podcast · Free (paid tier)  
  The AI engineer's newsletter and podcast: interviews with people building agents, models and infrastructure at the labs and startups. _The newsletter that named the AI engineer role. Its AINews digest condenses a day of AI Twitter, Discord and Reddit._

### Builders

People who ship with models and write about what works.

- **[Simon Willison's Weblog](https://simonwillison.net/)**  
  Simon Willison · Blog · Free  
  Near-daily notes on LLMs, tools, prompt injection and building with models, with links to everything he reads. _The best single feed for keeping current. The PyCon workshop (Stage 2) and the lethal trifecta (Stage 8) both come from here._
- **[Hamel Husain](https://hamel.dev/)**  
  Hamel Husain · Blog · Free  
  Evals, error analysis, LLM-as-judge and fine-tuning, from a consultant who builds AI products. _The source for 'Your AI Product Needs Evals' (Stage 2). Read his other evals posts as your projects grow._
- **[Eugene Yan](https://eugeneyan.com/writing/)**  
  Eugene Yan · Blog · Free  
  Applied ML and LLM systems: product evals, patterns for LLM systems, recommendation systems, working with AI. _Active in 2026. Strong on evals and on turning models into products (Track C)._
- **[Chip Huyen](https://huyenchip.com/blog/)**  
  Chip Huyen · Blog · Free  
  Long essays on AI engineering: agents, building a GenAI platform, common pitfalls. _Posting has slowed (latest January 2025), but 'Agents' and 'Building a Generative AI Platform' are still among the best overviews._
- **[Jason Liu](https://jxnl.co/writing/)**  
  Jason Liu · Blog · Free  
  Production RAG and retrieval, context engineering, coding agents, and the business side of shipping AI. _Creator of the instructor library for structured outputs (Stage 2). His RAG posts are direct and opinionated._
- **[Philipp Schmid](https://www.philschmid.de/)**  
  Philipp Schmid · Google DeepMind · Blog · Free  
  Practical guides on agents, harness engineering, computer use, evals and the Gemini API. _Active in 2026. His old fine-tuning notebooks are in Stage 6, and the blog has moved on to agents._

### Research explainers

Deep dives that turn papers into understanding.

- **[Ahead of AI](https://magazine.sebastianraschka.com/)**  
  Sebastian Raschka · Newsletter · Free (paid tier)  
  Research roundups and deep dives on LLM architectures, training and reasoning models. _Written by the author of LLMs-from-scratch (Stage 5). It's the most readable way to follow LLM research. His own site also has shorter Quick Notes that aren't in the newsletter._ Also: [sebastianraschka.com/blog](https://sebastianraschka.com/blog/)
- **[Lil'Log](https://lilianweng.github.io/)**  
  Lilian Weng · Blog · Free  
  Long, citation-heavy surveys: agents, hallucination, reward hacking, scaling laws, reasoning. _A few posts a year, each a definitive survey. Read them when you reach the matching stage._
- **[Andrej Karpathy's blog](https://karpathy.github.io/)**  
  Andrej Karpathy · Blog · Free  
  Rare, landmark posts on neural networks, from 'The Unreasonable Effectiveness of RNNs' to 2026's 'microgpt'. _Pairs with his Zero to Hero series (Stage 5)._
- **[Interconnects](https://www.interconnects.ai/)**  
  Nathan Lambert · Newsletter · Free (paid tier)  
  How frontier and open models are trained and released, especially post-training, RLHF and open-weight models. _Written by the author of the RLHF book. The best companion to Stage 6._
- **[Deep (Learning) Focus](https://cameronrwolfe.substack.com/)**  
  Cameron R. Wolfe · Newsletter · Free  
  Long, careful explainers of the research behind modern LLMs: training, alignment, reasoning, evaluation. _Slower to read than Ahead of AI but more thorough._
- **[Sebastian Ruder](https://www.ruder.io/)**  
  Sebastian Ruder · Blog · Free  
  NLP research, transfer learning, multilingual models, and his optimizer overview (Stage 4). _Research-leaning. Follow it if NLP is your focus._

### Labs

Where new models, techniques and system cards are announced.

- **[OpenAI Research](https://openai.com/news/research/)**  
  OpenAI · Lab blog · Free  
  OpenAI's research announcements: model releases, system cards, safety and alignment work, benchmarks. _Read the system cards and evals sections when a model launches, because those tell you what changed for builders. The filterable index is at openai.com/research/index._ Also: [Research index](https://openai.com/research/index/)
- **[Google Research Blog](https://research.google/blog/)**  
  Google Research · Lab blog · Free  
  Research posts across ML, agents, privacy and security, health and geospatial AI, filterable by label. _Broad. Filter by the Machine Intelligence or Natural Language Processing labels to keep it relevant._
- **[Engineering at Anthropic](https://www.anthropic.com/engineering)**  
  Anthropic · Lab blog · Free  
  How Anthropic builds agents and harnesses: context engineering, evals, Claude Code internals, containment, long-running agents. _The most practical lab blog for an AI engineer. Two Stage 7 and 8 core reads come from here._
- **[Hugging Face Blog](https://huggingface.co/blog)**  
  Hugging Face · Community blog · Free  
  Posts on open models, datasets, training and inference tooling, from Hugging Face and the community. _High volume and uneven. Sort by trending, and use it to keep up with open-weight models and the transformers, TRL and PEFT libraries._
- **[Google DeepMind Blog](https://deepmind.google/blog/)**  
  Google DeepMind · Lab blog · Free  
  Gemini model launches, research on reasoning and agents, and science applications. _Model announcements here link to technical reports, which are what to read._
- **[Anthropic Research](https://www.anthropic.com/research)**  
  Anthropic · Lab blog · Free  
  Interpretability, alignment, frontier red-team and economic-impact research. _Research rather than engineering. Engineering at Anthropic (above) is the practical one._
- **[AI at Meta Blog](https://ai.meta.com/blog/)**  
  Meta · Lab blog · Free  
  Open-weight model releases, research and applied AI from Meta. _Follow it for open-model releases._
- **[Connectionism](https://thinkingmachines.ai/blog/)**  
  Thinking Machines Lab · Lab blog · Free  
  Rare, very technical posts: LoRA Without Regret, On-Policy Distillation, Defeating Nondeterminism in LLM Inference. _Few posts, each excellent. 'LoRA Without Regret' belongs next to Stage 6._
- **[BAIR Blog](https://bair.berkeley.edu/blog/)**  
  UC Berkeley AI Research · Academic blog · Free  
  Accessible write-ups of Berkeley research before it reaches the mainstream. _Academic and broad, so skim the headlines._
- **[Claude Blog](https://claude.com/blog)**  
  Anthropic · Product blog · Free  
  Claude product news, best practices for agents and automations, and customer case studies. _Product-side and practical. Engineering at Anthropic covers the internals._
- **[LAION Blog](https://laion.ai/blog/)**  
  LAION · Non-profit blog · Free  
  Open datasets and models for multimodal research, from the non-profit behind LAION-5B. _Follow it for open multimodal data releases._

### Industry and impact

Where the market and the workplace are heading.

- **[One Useful Thing](https://www.oneusefulthing.org/)**  
  Ethan Mollick · Newsletter · Free  
  How AI changes work, education and organizations, from a Wharton professor who tests every model. _Useful for Track C: explaining AI to non-engineers._
- **[a16z AI](https://a16z.com/ai/)**  
  Andreessen Horowitz · VC blog · Free  
  Market maps, AI infrastructure analysis and AI-native startup trends. _An investor's view, so read it for where the market is going, not for technique. The LLM app stack (Stage 7) came from here._

### Tutorial sites

Look things up here when stuck. Quality varies by author, so check dates.

- **[Machine Learning Mastery](https://machinelearningmastery.com/)**  
  Jason Brownlee · Guiding Tech Media · Tutorial site · Free (paid ebooks)  
  Step-by-step tutorials from ML fundamentals and statistics to transformers, RAG and fine-tuning. _Good for looking up 'how do I do X in code' in Stages 1–3. Now part of a media group, so newer posts vary in depth._
- **[Towards Data Science](https://towardsdatascience.com/)**  
  TDS (independent since February 2025) · Publication · Free  
  Applied ML, data science and LLM tutorials and case studies from many authors. _It left Medium in 2025 and is now free to read. Quality depends on the author, so check dates and code against current docs._
- **[KDnuggets](https://www.kdnuggets.com/)**  
  Guiding Tech Media · News and tutorials · Free  
  Data science, ML and LLM tutorials, cheat sheets and career comparisons. _Light, quick reads. Its cheat sheets are the most useful part._
- **[Analytics Vidhya](https://www.analyticsvidhya.com/blog/)**  
  Analytics Vidhya · Tutorial site · Free (paid programs)  
  High-volume GenAI, RAG, agents and ML tutorials, plus interview prep. _Uneven and promotes its own paid programs. Use it as a search result, not a feed._

### Classic archives

No longer updated, but the explanations are still the best there are.

- **[Jay Alammar](https://jalammar.github.io/)**  
  Jay Alammar · Blog (archive) · Free  
  The visual explainers: The Illustrated Transformer, The Illustrated Word2vec, How GPT-3 Works. _Frozen, since new posts go to his Substack, but the illustrated posts are classics. The same author wrote Hands-On LLMs (Stage 5)._
- **[Distill](https://distill.pub/)**  
  Distill · Journal (archive) · Free  
  Peer-reviewed, interactive explanations of ML research: feature visualization, attention, graph neural networks. _On hiatus since July 2021, but the articles are still among the clearest explanations written._
- **[colah's blog](https://colah.github.io/)**  
  Chris Olah · Blog (archive) · Free  
  'Understanding LSTM Networks', 'Neural Networks, Manifolds, and Topology' and the start of the circuits line of interpretability work. _Read 'Understanding LSTM Networks' alongside Ng's Sequence Models (Stage 4). His newer work is published through Anthropic Research._

### Other blog lists

The lists this section was built from, for anyone who wants to dig further.

- **[The Ultimate AI Blog Guide: Who to Read and Why](https://aiconnections.substack.com/p/the-ultimate-ai-blog-guide-who-to)**  
  David Mataciunas · AI Connections · Blog list · Free  
  Ten individual blogs (Chip Huyen, Eugene Yan, Lilian Weng, Raschka, Willison, Karpathy, Lambert, Mollick, Gwern, Ruder) and seven company blogs, each with a one-line reason. _From May 2025. All but Gwern, Sakana and Sequoia are in the sections above._
- **[16 blogs to follow if you're serious about AI/ML](https://www.linkedin.com/posts/stasbel_if-youre-serious-about-growing-in-aiml-share-7425204247463579649-FkI1/)**  
  Stanislav Beliaev · LinkedIn · Blog list · Free  
  Karpathy, Chip Huyen, Raschka, Eugene Yan, Philipp Schmid, Hamel Husain, Jason Liu, Interconnects, Deep (Learning) Focus, BAIR, the big labs, The Batch and Thinking Machines. The comments add Latent Space, Jay Alammar and company engineering blogs. _All 16 are in the sections above._
- **[12 AI Blogs for Keeping Up With AI Trends](https://www.digitalocean.com/resources/articles/ai-blogs)**  
  DigitalOcean · Blog list · Free  
  Twelve blogs with a 'best suited for' line each, from research labs to tutorial sites and AI governance. _Updated December 2025. MarkTechPost, Towards AI, Holistic AI and DigitalOcean Community were left out above as aggregators or vendor content._
- **[10 Great ML and AI Blogs to Follow](https://www.tableau.com/learn/articles/blogs-about-machine-learning-artificial-intelligence)**  
  Tableau · Blog list · Free  
  An older list: OpenAI, Machine Learning Mastery, BAIR, Distill, FastML, AI Trends, Google AI and others. _Dated. FastML and AI Trends are inactive, and Distill is in Classic archives above. The site blocks automated readers, so it was checked through search._
- **[What are some good blogs to follow for AI/ML/DL/RL?](https://www.reddit.com/r/learnmachinelearning/comments/bgybcp/what_are_some_good_blogs_to_follow_for_aimldlrl/)**  
  r/learnmachinelearning · Forum thread · Free  
  A 2019 community thread of blog recommendations. _From 2019. Reddit couldn't be read automatically, so check the thread yourself. The recommendations that turned up elsewhere (Karpathy, colah, Distill, BAIR) are above._
- **[awesome-llm-blogs](https://github.com/yuxiang-gao/awesome-llm-blogs)**  
  yuxiang-gao · Link list · Free  
  A personal list of LLM blogs (OpenAI, Hugging Face, LAION, DeepMind, Jay Alammar, Su Jianlin's Scientific Spaces in Chinese) plus topic lists. _Small and from 2023. Su Jianlin, the author of RoPE, is the one source not above, and it's in Chinese._

### Maps and trackers

Landscapes, leaderboards and roadmaps. These items also appear in their stages.

- [ ] **[The AI Engineering Skills Map](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map)**  
  Andrew Ng · The Batch · Article series · ~1 h · Free  
  Ng's map of the AI engineer's job, built from 10,000+ job postings. It has four pillars: building and deploying AI apps, software fundamentals, using coding agents, and shaping the build. _Use it as the rubric for this route. Parts 3 and 5 are linked from side tracks B and C below._ Also: [Part 2: AI applications](https://www.deeplearning.ai/the-batch/he-ai-engineering-skills-map-in-detail-building-and-deploying-ai-applications), [Part 4: Coding agents](https://www.deeplearning.ai/the-batch/the-ai-engineering-skills-map-in-detail-using-coding-agents)
- [ ] **[AI Engineer Roadmap](https://roadmap.sh/ai-engineer)**  
  roadmap.sh · Roadmap · Free  
  An interactive topic map for applied AI engineers, with links per node. _Use it as a checklist against this route._
- [ ] **[LF AI & Data Landscape](https://landscape.lfai.foundation/)**  
  Linux Foundation · Ecosystem map · Free  
  A map of open-source AI and data projects. _Useful for getting oriented, not for learning._
- [ ] **[Emerging LLM App Stack](https://github.com/a16z-infra/llm-app-stack)**  
  a16z · Link list · ~1 h · Free  
  Tools listed by layer: data pipelines, embeddings, vector DBs, orchestration, eval, hosting. _A good mental model, but the tool lists stopped in February 2024 and predate agents and MCP. The companion article has the architecture diagram._ Also: [Companion article](https://a16z.com/emerging-architectures-for-llm-applications/)
- [ ] **[Artificial Analysis](https://artificialanalysis.ai/)**  
  Artificial Analysis · Leaderboard · Free  
  Independent comparison of models and API providers on intelligence, speed, latency and price. _Where to look when choosing a model for a project. Nothing else on the route covers this._
- [ ] **[LLM Architecture Gallery](https://sebastianraschka.com/llm-architecture-gallery/)**  
  Sebastian Raschka · Interactive reference · Free  
  Diagrams and fact sheets for about 109 current open models, with a compare tool and memory calculator. _Updated October 2026. Use it after LLMs-from-scratch to see how real models differ from your GPT._
- [ ] **[Hugging Face Papers (formerly Papers with Code)](https://huggingface.co/papers/trending)**  
  Hugging Face · Paper feed · Free  
  Trending research papers with code links. _paperswithcode.com now redirects here._
- [ ] **[best-of-ml-python](https://github.com/ml-tooling/best-of-ml-python)**  
  ml-tooling · Link list · Free  
  Ranked ML Python libraries by category. _Use it to compare libraries. Updates have slowed since March 2026._

## Research: techniques and the frontier

The techniques that move LLMs forward, each linked to its original paper, plus where to watch the frontier. **Standard** = used everywhere today, **Common** = widely used where it fits, **Emerging** = 2025–26 and promising, **Historical** = superseded but worth understanding.

### Track the frontier

**Paper feeds**

- **[Hugging Face Daily Papers](https://huggingface.co/papers)** (Daily) · Hugging Face  
  A community-upvoted daily selection of notable arXiv papers, linked to models, datasets and discussion. _The fastest curated filter on arXiv. The upvotes surface what practitioners care about._
- **[alphaXiv](https://www.alphaxiv.org)** (Daily) · alphaXiv  
  An arXiv discovery layer with trending papers, plain-language summaries and line-by-line discussion. _See which new papers are trending and ask questions about them in context._
- **[arXiv cs.CL (new papers)](https://arxiv.org/list/cs.CL/recent)** (Daily) · arXiv  
  The raw daily list of new NLP and LLM papers. _The primary source. Skim titles, or use it weekly once you know what you're looking for._
- **[arXiv cs.LG (new papers)](https://arxiv.org/list/cs.LG/recent)** (Daily) · arXiv  
  The daily list of new machine-learning papers, 300+ a day. _For training, optimization and RL papers not cross-listed to cs.CL. Use keyword alerts, because the volume is high._

**Research newsletters**

- **[Import AI](https://importai.substack.com)** (Weekly) · Jack Clark  
  Weekly analysis of a few important papers, with a focus on policy and safety. _Thoughtful selection and the implications, not just headlines._
- **[Last Week in AI](https://lastweekin.ai)** (Weekly) · Andrey Kurenkov et al.  
  A weekly news-and-research roundup with a companion podcast. _One broad weekly catch-up on models, research, policy and incidents._
- **[TLDR AI](https://tldr.tech/ai)** (Daily) · TLDR  
  A short daily email of AI news, research and tools for engineers. _A five-minute daily skim of launches and notable papers._
- **[AlphaSignal](https://alphasignal.ai)** (Live) · Alpha Signal  
  An upvote-ranked feed of new models, repos and papers, with a newsletter. _Its last-24-hours view shows which new repos and papers engineers are actually picking up._

**Leaderboards**

- **[Arena (formerly LMArena)](https://arena.ai/leaderboard)** (Live) · LMArena  
  Human-preference leaderboards for text, web development, vision, search, agents, images and video. _Perceived quality from blind votes. Read it with The Leaderboard Illusion in mind. lmarena.ai now redirects here._
- **[SWE-bench leaderboards](https://www.swebench.com)** (Live) · SWE-bench team  
  Official leaderboards for the Verified, Lite, Full, Multimodal and Multilingual variants. _Compare coding agents and models under the same harness._
- **[Epoch AI Benchmarking Hub](https://epoch.ai/benchmarks)** (Live) · Epoch AI  
  Independently run scores on 89 benchmarks, including FrontierMath, GPQA Diamond and SWE-bench Verified. _Comparable numbers and long-run capability trends._ Also: [Data Insights](https://epoch.ai/data-insights)
- **[Scale Labs leaderboards](https://labs.scale.com/leaderboard)** (Live) · Scale AI  
  Expert-built private leaderboards: Humanity's Last Exam, SWE-Bench Pro, MCP Atlas, Remote Labor Index and others. _Held-out test sets are less exposed to contamination, a check on public-benchmark claims._
- **[METR](https://metr.org)** (Monthly) · METR  
  Independent pre-deployment evaluations of frontier models and research on agent capability. _An outside view of what new models can really do on long tasks._
- **[ARC Prize leaderboard](https://arcprize.org/leaderboard)** (Live) · ARC Prize Foundation  
  Score versus cost on ARC-AGI-1, -2 and -3. _Tracks progress on fluid reasoning, and the cost per task, not just accuracy._

**Annual reports**

- **[State of AI Report](https://www.stateof.ai)** (Yearly (October)) · Nathan Benaich · Air Street Capital  
  An annual report on research, industry, politics and safety, with predictions graded the next year. _Read it each autumn to recalibrate on what changed._
- **[AI Index Report](https://hai.stanford.edu/ai-index)** (Yearly (April)) · Stanford HAI  
  An annual data compendium on research output, benchmarks, cost, investment and policy. _The citable source for long-run AI statistics._

### Prompting & reasoning (24)

_Learned in Stage 2._

- [ ] **[Few-shot / in-context learning](https://arxiv.org/abs/2005.14165)** · Standard · 2020  
  Language Models are Few-Shot Learners · Tom B. Brown et al. (OpenAI)  
  You put a few input-output examples in the prompt, and the model does the task without any weight updates. _It introduced the 'prompt instead of fine-tune' approach, and a few examples are still the cheapest way to pin down format and behavior._
- [ ] **[Chain-of-Thought (CoT)](https://arxiv.org/abs/2201.11903)** · Standard · 2022  
  Chain-of-Thought Prompting Elicits Reasoning in Large Language Models · Jason Wei et al. (Google)  
  The few-shot examples include worked-out intermediate reasoning steps, so the model writes out its reasoning before it answers. _It showed large gains on math and logic tasks, and step-by-step reasoning became the basis of later reasoning models._
- [ ] **[Zero-shot CoT ("Let's think step by step")](https://arxiv.org/abs/2205.11916)** · Common · 2022  
  Large Language Models are Zero-Shot Reasoners · Takeshi Kojima et al. (U. Tokyo / Google)  
  Adding one trigger phrase such as "Let's think step by step" gets the model to reason step by step without any examples. _It showed that reasoning can be unlocked with instructions alone. Today's reasoning models mostly do this on their own, so it matters mainly for non-reasoning models._
- [ ] **[Self-Consistency](https://arxiv.org/abs/2203.11171)** · Common · 2022  
  Self-Consistency Improves Chain of Thought Reasoning in Language Models · Xuezhi Wang et al. (Google)  
  You sample several reasoning paths at non-zero temperature and take a majority vote over their final answers. _It is the simplest way to trade extra compute for accuracy, and the baseline every test-time scaling method compares against._
- [ ] **[Tree of Thoughts (ToT)](https://arxiv.org/abs/2305.10601)** · Historical · 2023  
  Tree of Thoughts: Deliberate Problem Solving with Large Language Models · Shunyu Yao et al. (Princeton / Google DeepMind)  
  The model proposes and scores partial 'thoughts' and searches over them with breadth-first or depth-first search, backtracking when a path fails. _It framed LLM reasoning as search, which shaped later work on agent search and test-time compute. It is rarely used as-is now because of its cost._
- [ ] **[PAL / Program-aided reasoning](https://arxiv.org/abs/2211.10435)** · Common · 2022  
  PAL: Program-aided Language Models · Luyu Gao et al. (CMU)  
  The model writes its reasoning as code, and an interpreter runs that code to produce the answer. _Handing exact computation to code removes arithmetic errors, and it is the idea behind today's code-interpreter tools._
- [ ] **[Self-Refine](https://arxiv.org/abs/2303.17651)** · Common · 2023  
  Self-Refine: Iterative Refinement with Self-Feedback · Aman Madaan et al. (CMU / AI2)  
  The same model drafts an output, critiques it, and revises it in a loop, with no extra training. _It is the standard generate-critique-revise pattern behind many writing and coding pipelines, and works best when the critique can use concrete signals such as test results._
- [ ] **[Chain-of-Verification (CoVe)](https://arxiv.org/abs/2309.11495)** · Common · 2023  
  Chain-of-Verification Reduces Hallucination in Large Language Models · Shehzaad Dhuliawala et al. (Meta AI)  
  The model drafts an answer, writes verification questions about it, answers those separately, and then produces a corrected final answer. _A practical prompting recipe for reducing factual hallucinations in long-form answers and lists._
- [ ] **[DSPy (programmatic prompt optimization)](https://arxiv.org/abs/2310.03714)** · Common · 2023  
  DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines · Omar Khattab et al. (Stanford)  
  You declare LLM pipeline steps as modules with input and output signatures, and an optimizer 'compiles' them by searching over instructions and few-shot examples against a metric. _It replaces hand-tuned prompt strings with metric-driven optimization and is the main framework for doing so._
- [ ] **[Process reward models (step-level verification)](https://arxiv.org/abs/2305.20050)** · Common · 2023  
  Let's Verify Step by Step · Hunter Lightman et al. (OpenAI)  
  It trains a verifier that scores each reasoning step instead of only the final answer, then uses it to pick the best of many sampled solutions. _It introduced process reward models and the PRM800K dataset, a key ingredient of verifier-guided search and reasoning-model training._
- [ ] **[Reasoning models (OpenAI o1)](https://arxiv.org/abs/2412.16720)** · Standard · 2024  
  OpenAI o1 System Card · OpenAI  
  o1 is trained with reinforcement learning to produce a long hidden chain of thought before it answers, so accuracy scales with how long it thinks. _It started the reasoning-model era. Thinking or effort settings are now a standard knob on frontier models._
- [ ] **[DeepSeek-R1 (RL for reasoning)](https://arxiv.org/abs/2501.12948)** · Standard · 2025  
  DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning · DeepSeek-AI  
  Large-scale RL with rule-based, verifiable rewards (GRPO) produces long chain-of-thought reasoning with little supervised data, and the reasoning can then be distilled into smaller models. _The first open-weights model to match o1-level reasoning, with a published recipe the open ecosystem then widely copied._
- [ ] **[Compute-optimal test-time scaling](https://arxiv.org/abs/2408.03314)** · Common · 2024  
  Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters · Charlie Snell et al. (UC Berkeley / Google DeepMind)  
  It compares ways of spending inference compute (best-of-N, verifier-guided search, sequential revision) and allocates compute by how hard each prompt is. _It established that spending more compute at inference can beat a bigger model, the theory behind 'think longer' settings._
- [ ] **[s1 / budget forcing](https://arxiv.org/abs/2501.19393)** · Emerging · 2025  
  s1: Simple test-time scaling · Niklas Muennighoff et al. (Stanford)  
  Fine-tuning on only 1,000 curated reasoning traces, plus 'budget forcing' (appending "Wait" to extend thinking, or cutting it off), gives controllable test-time scaling. _It showed reasoning can be unlocked cheaply and that thinking length can be controlled with a simple decoding trick._
- [ ] **[Lost in the Middle](https://arxiv.org/abs/2307.03172)** · Common · 2023  
  Lost in the Middle: How Language Models Use Long Contexts · Nelson F. Liu et al. (Stanford)  
  It shows that models use information at the start and end of a long context much better than information in the middle. _It is why key instructions and the most relevant retrieved chunks go at the edges of the prompt, and why a bigger context window is not the same as good recall._
- [ ] **[Least-to-Most prompting](https://arxiv.org/abs/2205.10625)** · Historical · 2022  
  Least-to-Most Prompting Enables Complex Reasoning in Large Language Models · Denny Zhou et al. (Google)  
  The model first breaks a problem into simpler subproblems, then solves them in order, feeding each answer into the next. _The origin of explicit decomposition prompting, still the right move when a task has clear sub-steps._
- [ ] **[Graph of Thoughts](https://arxiv.org/abs/2308.09687)** · Historical · 2023  
  Graph of Thoughts: Solving Elaborate Problems with Large Language Models · Maciej Besta et al. (ETH Zurich)  
  Generalizes Tree of Thoughts so thoughts form a graph that can be merged, refined and looped back on. _Shows how far structured reasoning can go. Mostly of research interest now._
- [ ] **[Plan-and-Solve](https://arxiv.org/abs/2305.04091)** · Historical · 2023  
  Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models · Lei Wang et al.  
  Asks the model to first write a plan and then carry it out step by step, without examples. _An early form of the plan-then-execute pattern used by today's agents._
- [ ] **[Step-Back prompting](https://arxiv.org/abs/2310.06117)** · Common · 2023  
  Take a Step Back: Evoking Reasoning via Abstraction in Large Language Models · Huaixiu Steven Zheng et al. (Google DeepMind)  
  The model first asks a more general 'step-back' question about the underlying principle, answers it, and then uses that to answer the original question. _Also used in RAG as a query transformation, retrieving on the general question as well as the specific one._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/query_transformations.ipynb)
- [ ] **[Program of Thoughts](https://arxiv.org/abs/2211.12588)** · Historical · 2022  
  Program of Thoughts Prompting: Disentangling Computation from Reasoning for Numerical Reasoning Tasks · Wenhu Chen et al.  
  Like PAL, the model expresses reasoning as a program and an interpreter does the computation. _Parallel work to PAL that confirmed code is a better medium than text for numerical reasoning._
- [ ] **[Skeleton-of-Thought](https://arxiv.org/abs/2307.15337)** · Historical · 2023  
  Skeleton-of-Thought: Prompting LLMs for Efficient Parallel Generation · Xuefei Ning et al.  
  The model writes an outline first, then expands each point in parallel calls. _A latency trick for long answers: parallel expansion cuts wall-clock time._
- [ ] **[APE (automatic prompt engineer)](https://arxiv.org/abs/2211.01910)** · Historical · 2022  
  Large Language Models Are Human-Level Prompt Engineers · Yongchao Zhou et al.  
  An LLM proposes candidate instructions and the best-scoring one on a dev set is kept. _The first automatic prompt optimization, a forerunner of DSPy._
- [ ] **[OPRO (LLMs as optimizers)](https://arxiv.org/abs/2309.03409)** · Historical · 2023  
  Large Language Models as Optimizers · Chengrun Yang et al. (Google DeepMind)  
  The LLM iteratively proposes better prompts given past prompts and their scores. _Showed prompts can be optimized like any other parameter, using the model itself as the optimizer._
- [ ] **[STaR (self-taught reasoner)](https://arxiv.org/abs/2203.14465)** · Historical · 2022  
  STaR: Bootstrapping Reasoning With Reasoning · Eric Zelikman et al. (Stanford)  
  The model generates rationales, keeps the ones that lead to correct answers, and fine-tunes on them, repeating the loop. _An early version of training on the model's own successful reasoning, the idea behind modern reasoning RL._

### RAG & retrieval (41)

_Learned in Stage 7._

**Foundations**

- [ ] **[RAG (Retrieval-Augmented Generation)](https://arxiv.org/abs/2005.11401)** · Historical · 2020  
  Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks · Patrick Lewis et al. (Meta AI)  
  Combines a neural retriever over a document index with a generator, so the model conditions its answers on retrieved passages. _The paper that named and defined RAG. Every retrieve-then-generate pipeline descends from it._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/simple_rag.ipynb)
- [ ] **[REALM](https://arxiv.org/abs/2002.08909)** · Historical · 2020  
  REALM: Retrieval-Augmented Language Model Pre-Training · Kelvin Guu et al. (Google)  
  Pre-trains a language model together with a learned retriever that fetches Wikipedia documents during training. _Showed retrieval can be learned end to end and makes knowledge explicit and updatable, a precursor to RAG._
- [ ] **[RETRO](https://arxiv.org/abs/2112.04426)** · Historical · 2021  
  Improving language models by retrieving from trillions of tokens · Sebastian Borgeaud et al. (DeepMind)  
  A language model that cross-attends to chunks retrieved from a 2-trillion-token database and matches much larger models. _Key evidence that retrieval can substitute for parameter count._
- [ ] **[DPR (Dense Passage Retrieval)](https://arxiv.org/abs/2004.04906)** · Standard · 2020  
  Dense Passage Retrieval for Open-Domain Question Answering · Vladimir Karpukhin et al. (Meta AI)  
  Trains a question encoder and a passage encoder so relevant passages land near the question in embedding space. _Established the bi-encoder dense-retrieval recipe behind every vector-database RAG system._
- [ ] **[BM25 / hybrid search](https://doi.org/10.1561/1500000019)** · Standard · 2009  
  The Probabilistic Relevance Framework: BM25 and Beyond · Stephen Robertson & Hugo Zaragoza  
  BM25 scores documents by term frequency, rarity and length, and hybrid search combines it with dense vector scores. _Keyword search still catches exact names, codes and rare terms that embeddings miss, so hybrid is the default production baseline._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/fusion_retrieval.ipynb)
- [ ] **[ColBERT (late interaction)](https://arxiv.org/abs/2004.12832)** · Common · 2020  
  ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT · Omar Khattab & Matei Zaharia (Stanford)  
  Stores one embedding per token and scores a document by summing each query token's best match (MaxSim). ColBERTv2 compresses the vectors to make it practical. _Near-cross-encoder quality at retrieval speed, and the basis of ColPali and many modern retrievers._ Also: [ColBERTv2](https://arxiv.org/abs/2112.01488)
- [ ] **[Sentence-BERT](https://arxiv.org/abs/1908.10084)** · Standard · 2019  
  Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks · Nils Reimers & Iryna Gurevych  
  Fine-tunes BERT in a siamese setup to produce sentence embeddings you can compare with cosine similarity. _Made semantic embeddings cheap. The sentence-transformers library is still the standard way to run open embedding models._
- [ ] **[MTEB](https://arxiv.org/abs/2210.07316)** · Standard · 2022  
  MTEB: Massive Text Embedding Benchmark · Niklas Muennighoff et al. (Hugging Face)  
  Evaluates embedding models across retrieval, clustering, classification and similarity tasks in many languages. _Its leaderboard is the usual starting point for choosing an embedding model, but check the retrieval subset and your own data._
- [ ] **[Matryoshka embeddings](https://arxiv.org/abs/2205.13147)** · Common · 2022  
  Matryoshka Representation Learning · Aditya Kusupati et al.  
  Trains embeddings so their leading dimensions are also good embeddings, so vectors can be truncated to smaller sizes. _Lets you trade accuracy for storage and speed, and most current embedding APIs support it._

**Query transformation**

- [ ] **[HyDE](https://arxiv.org/abs/2212.10496)** · Common · 2022  
  Precise Zero-Shot Dense Retrieval without Relevance Labels · Luyu Gao et al. (CMU)  
  An LLM writes a hypothetical answer, and you retrieve with that answer's embedding instead of the question's. _A cheap way to close the gap between short questions and long documents, especially in new domains._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/HyDe_Hypothetical_Document_Embedding.ipynb)
- [ ] **[Reciprocal Rank Fusion (RRF)](https://doi.org/10.1145/1571941.1572114)** · Standard · 2009  
  Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods · Gordon V. Cormack et al. (Waterloo)  
  Merges several ranked lists by summing 1/(k + rank) for each document. _The simple, tuning-free default for fusing BM25 and dense results, or results from several query variants._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/fusion_retrieval.ipynb)
- [ ] **[Multi-query / RAG-Fusion](https://arxiv.org/abs/2402.03367)** · Common · 2024  
  RAG-Fusion: a New Take on Retrieval-Augmented Generation · Zackary Rackauckas  
  An LLM writes several reformulations of the query, you retrieve for each and fuse the results with RRF. _Improves recall for vague questions, at the cost of extra LLM and retrieval calls._
- [ ] **[Query decomposition (Self-Ask)](https://arxiv.org/abs/2210.03350)** · Common · 2022  
  Measuring and Narrowing the Compositionality Gap in Language Models · Ofir Press et al.  
  The model breaks a multi-hop question into explicit sub-questions, each answered with search. _The basis for sub-query decomposition in multi-hop RAG: retrieve per sub-question, then combine._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/query_transformations.ipynb)
- [ ] **[Query2doc](https://arxiv.org/abs/2303.07678)** · Common · 2023  
  Query2doc: Query Expansion with Large Language Models · Liang Wang et al. (Microsoft)  
  Expands the query with an LLM-written pseudo-document before sparse or dense retrieval. _Simple query expansion that notably boosts BM25 as well as dense retrievers._
- [ ] **[Rewrite-Retrieve-Read](https://arxiv.org/abs/2305.14283)** · Common · 2023  
  Query Rewriting for Retrieval-Augmented Large Language Models · Xinbei Ma et al.  
  Adds a query-rewriting step, by an LLM or a small rewriter trained with RL, before retrieval. _Made query rewriting a pipeline stage, now standard for conversational and messy queries._

**Chunking & indexing**

- [ ] **[RAPTOR](https://arxiv.org/abs/2401.18059)** · Common · 2024  
  RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval · Parth Sarthi et al. (Stanford)  
  Recursively clusters and summarizes chunks into a tree, then retrieves across levels from detail to summary. _For questions that need whole-document or thematic understanding that flat chunks can't give._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/raptor.ipynb)
- [ ] **[Late chunking](https://arxiv.org/abs/2409.04701)** · Emerging · 2024  
  Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models · Michael Günther et al. (Jina AI)  
  Embeds the whole document with a long-context model first, then pools token embeddings per chunk so each chunk carries document context. _Fixes lost context (pronouns, references) in chunk embeddings without extra LLM calls._
- [ ] **[Proposition indexing (Dense X Retrieval)](https://arxiv.org/abs/2312.06648)** · Emerging · 2023  
  Dense X Retrieval: What Retrieval Granularity Should We Use? · Tong Chen et al.  
  An LLM splits text into atomic, self-contained propositions, and those are indexed instead of passages. _Shows that retrieval granularity matters. Finer units improve precision for fact-seeking queries._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/proposition_chunking.ipynb)
- [ ] **[Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)** · Common · 2024  
  Introducing Contextual Retrieval · Anthropic  
  An LLM prepends a short, document-aware context to each chunk before embedding and BM25 indexing, combined with reranking. _A practical, widely adopted way to cut retrieval failures, made cheap by prompt caching._

**Reranking**

- [ ] **[Cross-encoder reranking (monoBERT)](https://arxiv.org/abs/1901.04085)** · Standard · 2019  
  Passage Re-ranking with BERT · Rodrigo Nogueira & Kyunghyun Cho  
  Scores each query-passage pair jointly with BERT to rerank the top candidates from a first-stage retriever. _Retrieve-then-rerank with a cross-encoder is the standard way to raise precision in production RAG._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/reranking.ipynb)
- [ ] **[RankGPT (LLM listwise reranking)](https://arxiv.org/abs/2304.09542)** · Common · 2023  
  Is ChatGPT Good at Search? Investigating Large Language Models as Re-Ranking Agents · Weiwei Sun et al.  
  Prompts an LLM to reorder a list of candidate passages by relevance, using a sliding window. _Started LLM-based reranking, which trades higher cost for better zero-shot quality._
- [ ] **[Reasoning rerankers (Rank1)](https://arxiv.org/abs/2502.18418)** · Emerging · 2025  
  Rank1: Test-Time Compute for Reranking in Information Retrieval · Orion Weller et al. (JHU)  
  A reranker distilled from reasoning-model traces that thinks before it judges relevance. _Reasoning rerankers excel on reasoning-heavy queries where similarity matching fails._

**Graph & structured**

- [ ] **[GraphRAG](https://arxiv.org/abs/2404.16130)** · Common · 2024  
  From Local to Global: A Graph RAG Approach to Query-Focused Summarization · Darren Edge et al. (Microsoft Research)  
  Builds an LLM-extracted entity graph, detects communities and pre-summarizes them to answer whole-corpus questions. _For questions about a whole dataset (themes, overviews) that chunk retrieval can't answer. Indexing is expensive._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/Microsoft_GraphRag.ipynb)
- [ ] **[LightRAG](https://arxiv.org/abs/2410.05779)** · Emerging · 2024  
  LightRAG: Simple and Fast Retrieval-Augmented Generation · Zirui Guo et al. (HKU)  
  Graph-structured indexing with dual-level (entity and theme) retrieval and incremental updates. _A cheaper, more updatable alternative to GraphRAG, popular in open-source stacks._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/light_rag.ipynb)
- [ ] **[HippoRAG](https://arxiv.org/abs/2405.14831)** · Emerging · 2024  
  HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models · Bernal Jiménez Gutiérrez et al. (Ohio State)  
  Builds a knowledge graph and runs Personalized PageRank from the query's entities to retrieve for multi-hop questions in one step. _Efficient multi-hop retrieval without iterative LLM calls, and a reference design for graph memory._ Also: [HippoRAG 2 (2025)](https://arxiv.org/abs/2502.14802)
- [ ] **[Text-to-SQL (DIN-SQL)](https://arxiv.org/abs/2304.11015)** · Common · 2023  
  DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction · Mohammadreza Pourreza & Davood Rafiei  
  Splits text-to-SQL into schema linking, classification, generation and self-correction steps. _For structured data, generating a query beats embedding tables, and decomposition with self-correction remains the core pattern._

**Self-reflective & adaptive**

- [ ] **[Self-RAG](https://arxiv.org/abs/2310.11511)** · Common · 2023  
  Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection · Akari Asai et al. (UW / AI2)  
  Trains a model to emit reflection tokens that decide when to retrieve and to critique retrieved passages and its own output. _The canonical example of a model deciding when to retrieve and whether to trust what it got._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/self_rag.ipynb)
- [ ] **[CRAG (Corrective RAG)](https://arxiv.org/abs/2401.15884)** · Common · 2024  
  Corrective Retrieval Augmented Generation · Shi-Qi Yan et al.  
  An evaluator grades retrieved documents, then the system keeps them, refines them or falls back to web search. _A popular guard against bad retrieval before generating, common in LangGraph examples._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/crag.ipynb)
- [ ] **[Adaptive-RAG](https://arxiv.org/abs/2403.14403)** · Common · 2024  
  Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity · Soyeong Jeong et al. (KAIST)  
  A classifier predicts query complexity and routes each query to no retrieval, single-step or multi-step retrieval. _Routing saves cost on easy questions while handling hard ones properly._
- [ ] **[FLARE (active retrieval)](https://arxiv.org/abs/2305.06983)** · Emerging · 2023  
  Active Retrieval Augmented Generation · Zhengbao Jiang et al. (CMU)  
  During long-form generation, retrieves again whenever the upcoming sentence contains low-confidence tokens. _Introduced retrieving during generation instead of only once up front._
- [ ] **[IRCoT](https://arxiv.org/abs/2212.10509)** · Common · 2022  
  Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions · Harsh Trivedi et al. (Stony Brook / AI2)  
  Alternates chain-of-thought steps with retrieval, using each reasoning step as the next search query. _A foundational multi-hop pattern that today's agentic search loops generalize._
- [ ] **[Agentic RAG](https://arxiv.org/abs/2501.09136)** · Standard · 2025  
  Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG · Aditi Singh et al.  
  Agents plan, call retrieval tools, reflect and iterate instead of running a fixed retrieve-then-generate pipeline. _Search as a tool inside an agent loop is the dominant RAG architecture in 2025–26._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/Agentic_RAG.ipynb)
- [ ] **[Search-R1 (RL-trained search agents)](https://arxiv.org/abs/2503.09516)** · Emerging · 2025  
  Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning · Bowen Jin et al. (UIUC)  
  Uses RL with outcome rewards to train a model to interleave reasoning with multiple search calls. _A key open recipe behind deep-research models that learn when and what to search._
- [ ] **[Search-o1](https://arxiv.org/abs/2501.05366)** · Emerging · 2025  
  Search-o1: Agentic Search-Enhanced Large Reasoning Models · Xiaoxi Li et al. (Renmin U.)  
  Lets a reasoning model call search mid-thought when it hits a knowledge gap, then condenses the results back into its reasoning. _A training-free way to add search to reasoning models._

**Evaluation & long context**

- [ ] **[RAGAS](https://arxiv.org/abs/2309.15217)** · Standard · 2023  
  Ragas: Automated Evaluation of Retrieval Augmented Generation · Shahul Es et al.  
  Reference-free, LLM-judged metrics for RAG: faithfulness, answer relevance and context relevance. _The most widely used open-source RAG evaluation framework and metric vocabulary._
- [ ] **[ARES](https://arxiv.org/abs/2311.09476)** · Emerging · 2023  
  ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems · Jon Saad-Falcon et al. (Stanford)  
  Trains small judges on synthetic data and uses a small human-labeled set to score RAG systems with confidence intervals. _A more statistically grounded alternative to pure LLM-as-judge evaluation._
- [ ] **[BRIGHT (reasoning-heavy retrieval)](https://arxiv.org/abs/2407.12883)** · Emerging · 2024  
  BRIGHT: A Realistic and Challenging Benchmark for Reasoning-Intensive Retrieval · Hongjin Su et al.  
  A retrieval benchmark where finding the right document needs reasoning, not just keyword or semantic overlap. _Shows where standard embeddings fail and drives reasoning retrievers._
- [ ] **[RAG survey (Naive, Advanced, Modular)](https://arxiv.org/abs/2312.10997)** · Standard · 2023  
  Retrieval-Augmented Generation for Large Language Models: A Survey · Yunfan Gao et al. (Tongji / Fudan)  
  Surveys RAG across retrieval, generation and augmentation and introduces the Naive, Advanced and Modular RAG taxonomy. _The standard overview and vocabulary for the RAG design space._

**New retrieval models**

- [ ] **[ColPali (visual document retrieval)](https://arxiv.org/abs/2407.01449)** · Emerging · 2024  
  ColPali: Efficient Document Retrieval with Vision Language Models · Manuel Faysse et al.  
  Embeds page images directly with a vision-language model and ColBERT-style late interaction, skipping OCR and parsing. _The go-to approach for PDFs full of tables, charts and layout._ Also: [Tutorial notebook](https://github.com/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/multi_model_rag_with_colpali.ipynb)
- [ ] **[ReasonIR](https://arxiv.org/abs/2504.20595)** · Emerging · 2025  
  ReasonIR: Training Retrievers for Reasoning Tasks · Rulin Shao et al. (Meta / UW)  
  A retriever trained on synthetic, reasoning-heavy queries so it finds documents that help reasoning, not just similar text. _Part of the 2025 move toward retrievers built for reasoning models._
- [ ] **[MUVERA](https://arxiv.org/abs/2405.19504)** · Emerging · 2024  
  MUVERA: Multi-Vector Retrieval via Fixed Dimensional Encodings · Laxman Dhulipala et al. (Google)  
  Turns multi-vector (ColBERT-style) representations into single fixed-size vectors so standard vector search can serve them. _Makes late-interaction quality affordable on ordinary vector databases._

### Agents & tool use (22)

_Learned in Stage 8._

- [ ] **[ReAct](https://arxiv.org/abs/2210.03629)** · Standard · 2022  
  ReAct: Synergizing Reasoning and Acting in Language Models · Shunyu Yao et al. (Princeton / Google)  
  The model alternates between reasoning ('Thought'), tool calls ('Action') and tool results ('Observation') in a loop until the task is done. _The canonical agent loop. Almost every agent framework and coding agent is a variant of it._
- [ ] **[Toolformer](https://arxiv.org/abs/2302.04761)** · Historical · 2023  
  Toolformer: Language Models Can Teach Themselves to Use Tools · Timo Schick et al. (Meta AI)  
  The model learns in a self-supervised way where to insert API calls (calculator, search and so on) by keeping only the calls that improve its next-token predictions. _It showed tool use can be trained into a model, which led to native function calling. Today this comes from post-training rather than this exact method._
- [ ] **[Reflexion](https://arxiv.org/abs/2303.11366)** · Common · 2023  
  Reflexion: Language Agents with Verbal Reinforcement Learning · Noah Shinn et al. (Northeastern / MIT / Princeton)  
  After a failed attempt, the agent writes a verbal self-reflection into memory and uses it to do better on the next try, with no weight updates. _It popularized learning from feedback across attempts, such as retrying after failing tests, a common pattern in coding agents._
- [ ] **[Voyager (skill library)](https://arxiv.org/abs/2305.16291)** · Historical · 2023  
  Voyager: An Open-Ended Embodied Agent with Large Language Models · Guanzhi Wang et al. (NVIDIA / Caltech)  
  A Minecraft agent that sets itself a curriculum, writes code-based skills, checks them, and stores them in a growing library it retrieves from later. _It introduced agents that build up reusable, retrievable skills, an idea that runs through to today's agent skill systems._
- [ ] **[Generative Agents (memory stream)](https://arxiv.org/abs/2304.03442)** · Common · 2023  
  Generative Agents: Interactive Simulacra of Human Behavior · Joon Sung Park et al. (Stanford / Google)  
  Simulated characters keep a memory stream of observations, retrieve memories by recency, importance and relevance, and periodically reflect and plan. _It defined the standard agent-memory architecture (retrieval scoring plus reflection) and launched LLM-based social simulation._
- [ ] **[MemGPT (virtual context management)](https://arxiv.org/abs/2310.08560)** · Common · 2023  
  MemGPT: Towards LLMs as Operating Systems · Charles Packer et al. (UC Berkeley)  
  The agent manages its own memory tiers, paging information between the context window and external storage through function calls, like an OS handles virtual memory. _The reference design for long-lived agents with persistent memory (it became Letta), and an early example of context engineering._
- [ ] **[CodeAct (code as action)](https://arxiv.org/abs/2402.01030)** · Common · 2024  
  Executable Code Actions Elicit Better LLM Agents · Xingyao Wang et al. (UIUC)  
  The agent acts by writing and running Python code instead of JSON tool calls, so it can chain tools, loop and handle errors within one action. _Often more efficient and capable than JSON tool calling, and the basis of OpenHands and code-execution approaches to tool use._
- [ ] **[SWE-agent (agent-computer interface)](https://arxiv.org/abs/2405.15793)** · Common · 2024  
  SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering · John Yang et al. (Princeton)  
  It designs tools built for LLMs (file viewer, search, editing with lint checks) so the agent can navigate and fix real repositories. _It introduced agent-computer interface design: tool ergonomics matter as much as the model. That became a core principle of coding agents._
- [ ] **[AutoGen (multi-agent conversation)](https://arxiv.org/abs/2308.08155)** · Common · 2023  
  AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation · Qingyun Wu et al. (Microsoft Research)  
  A framework where several configurable agents (LLMs, tools, humans) solve tasks by talking to each other. _The reference paper for multi-agent orchestration. Use several agents when work splits into separable roles or parallel subtasks, and one agent otherwise._
- [ ] **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/specification/latest)** · Standard · 2024  
  Model Context Protocol Specification · Anthropic (now an open community standard)  
  An open JSON-RPC protocol through which servers expose tools, resources and prompts to any LLM host application. _The de facto standard for connecting agents to tools and data: write an integration once and use it from any client._
- [ ] **[Agent Skills (progressive disclosure)](https://agentskills.io/home)** · Emerging · 2025  
  Agent Skills open standard · Anthropic (open standard)  
  A skill is a folder with a SKILL.md (name, description, instructions) plus optional scripts and resources, and the agent reads only the descriptions until a task needs the full instructions. _It packages procedures and know-how cheaply in context. Released as an open standard in December 2025 and supported by Claude Code, Codex, Gemini CLI, Cursor, GitHub Copilot and others._
- [ ] **[SWE-bench](https://arxiv.org/abs/2310.06770)** · Standard · 2023  
  SWE-bench: Can Language Models Resolve Real-World GitHub Issues? · Carlos E. Jimenez et al. (Princeton)  
  A benchmark where an agent must resolve real GitHub issues in Python repos, scored by whether the repo's tests pass. _The headline benchmark for coding agents, with a human-validated Verified subset. It is how agentic coding progress is tracked._
- [ ] **[WebArena](https://arxiv.org/abs/2307.13854)** · Common · 2023  
  WebArena: A Realistic Web Environment for Building Autonomous Agents · Shuyan Zhou et al. (CMU)  
  Self-hosted, realistic websites (shopping, forums, GitLab, CMS) with long-horizon tasks, checked by verifying the end state. _The standard reproducible benchmark for browser and web agents._
- [ ] **[OSWorld (computer use)](https://arxiv.org/abs/2404.07972)** · Common · 2024  
  OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments · Tianbao Xie et al. (HKU)  
  Runs agents in real operating systems inside VMs, where they complete tasks from screenshots using mouse and keyboard. _The main yardstick for computer-use agents that operate GUIs like a person._
- [ ] **[tau-bench (tool-agent-user)](https://arxiv.org/abs/2406.12045)** · Common · 2024  
  τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains · Shunyu Yao et al. (Sierra)  
  An agent follows domain policies and uses APIs while a simulated user talks to it (airline, retail), and pass^k measures consistency across repeated trials. _It tests what production customer-facing agents need: following rules, multi-turn tool use and reliability._
- [ ] **[MRKL systems](https://arxiv.org/abs/2205.00445)** · Historical · 2022  
  MRKL Systems: A modular, neuro-symbolic architecture that combines large language models, external knowledge sources and discrete reasoning · Ehud Karpas et al. (AI21)  
  An LLM routes each query to the right expert module, such as a calculator, database or API. _One of the first tool-routing architectures, a forerunner of function calling._
- [ ] **[Gorilla](https://arxiv.org/abs/2305.15334)** · Common · 2023  
  Gorilla: Large Language Model Connected with Massive APIs · Shishir G. Patil et al. (UC Berkeley)  
  A model fine-tuned to write correct API calls, with retrieval over API documentation to reduce hallucinated calls. _Its Berkeley Function-Calling Leaderboard is still a standard way to compare tool-calling models._
- [ ] **[LATS (Language Agent Tree Search)](https://arxiv.org/abs/2310.04406)** · Historical · 2023  
  Language Agent Tree Search Unifies Reasoning Acting and Planning in Language Models · Andy Zhou et al.  
  Combines ReAct-style acting with Monte Carlo tree search, using self-reflection as a value signal. _Shows how search improves agents on hard tasks, at a high compute cost._
- [ ] **[OpenHands](https://arxiv.org/abs/2407.16741)** · Common · 2024  
  OpenHands: An Open Platform for AI Software Developers as Generalist Agents · Xingyao Wang et al.  
  An open-source platform for coding agents that act through code, a shell and a browser in a sandbox. _The main open-source coding-agent platform, used in research and in CMU's agents course._
- [ ] **[MetaGPT](https://arxiv.org/abs/2308.00352)** · Historical · 2023  
  MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework · Sirui Hong et al.  
  Assigns software-company roles (product manager, architect, engineer) to agents that follow standard operating procedures. _An influential example of role-based multi-agent design._
- [ ] **[HuggingGPT](https://arxiv.org/abs/2303.17580)** · Historical · 2023  
  HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face · Yongliang Shen et al. (Zhejiang U. / Microsoft)  
  An LLM plans a task and delegates parts to specialist models from the Hugging Face Hub. _An early LLM-as-orchestrator design._
- [ ] **[AgentBench](https://arxiv.org/abs/2308.03688)** · Historical · 2023  
  AgentBench: Evaluating LLMs as Agents · Xiao Liu et al. (Tsinghua)  
  Evaluates LLMs as agents across eight environments, from operating systems and databases to games and web shopping. _One of the first broad agent benchmarks._

### Training & alignment (15)

_Learned in Stage 6._

- [ ] **[InstructGPT / RLHF](https://arxiv.org/abs/2203.02155)** · Standard · 2022  
  Training language models to follow instructions with human feedback · Long Ouyang et al. (OpenAI)  
  Supervised fine-tuning, then a reward model trained on human rankings, then PPO against that reward model. _The recipe behind ChatGPT and the reference point for all later post-training._
- [ ] **[Constitutional AI / RLAIF](https://arxiv.org/abs/2212.08073)** · Common · 2022  
  Constitutional AI: Harmlessness from AI Feedback · Yuntao Bai et al. (Anthropic)  
  Trains a harmless assistant with AI-generated critiques, revisions and preference labels guided by written principles. _Made AI feedback a scalable replacement for much human labeling._
- [ ] **[DPO](https://arxiv.org/abs/2305.18290)** · Standard · 2023  
  Direct Preference Optimization: Your Language Model is Secretly a Reward Model · Rafael Rafailov et al. (Stanford)  
  Trains directly on preference pairs with a simple classification-style loss, with no reward model or RL loop. _The default lightweight preference-tuning method in open-source stacks such as TRL._
- [ ] **[KTO](https://arxiv.org/abs/2402.01306)** · Common · 2024  
  KTO: Model Alignment as Prospect Theoretic Optimization · Kawin Ethayarajh et al. (Stanford / Contextual AI)  
  Aligns models from single thumbs-up or thumbs-down labels instead of paired preferences. _Lets teams use the cheap binary feedback found in production logs._
- [ ] **[GRPO](https://arxiv.org/abs/2402.03300)** · Standard · 2024  
  DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models · Zhihong Shao et al. (DeepSeek)  
  Introduces Group Relative Policy Optimization, a PPO variant that replaces the value network with rewards normalized within a group of samples. _GRPO and its variants are the workhorse RL algorithms for training reasoning models._
- [ ] **[LoRA](https://arxiv.org/abs/2106.09685)** · Standard · 2021  
  LoRA: Low-Rank Adaptation of Large Language Models · Edward J. Hu et al. (Microsoft)  
  Freezes the pretrained weights and trains small low-rank update matrices. _The default parameter-efficient fine-tuning method, enabling cheap per-task adapters._
- [ ] **[QLoRA](https://arxiv.org/abs/2305.14314)** · Standard · 2023  
  QLoRA: Efficient Finetuning of Quantized LLMs · Tim Dettmers et al. (UW)  
  Trains LoRA adapters on top of a frozen 4-bit quantized base model. _Made fine-tuning large models possible on one GPU, and is the standard budget recipe._
- [ ] **[DoRA](https://arxiv.org/abs/2402.09353)** · Common · 2024  
  DoRA: Weight-Decomposed Low-Rank Adaptation · Shih-Yang Liu et al. (NVIDIA / HKUST)  
  Splits each weight into magnitude and direction and applies LoRA only to the direction. _A drop-in LoRA upgrade, supported in Hugging Face PEFT, that narrows the gap to full fine-tuning._
- [ ] **[Instruction tuning (FLAN)](https://arxiv.org/abs/2109.01652)** · Standard · 2021  
  Finetuned Language Models Are Zero-Shot Learners · Jason Wei et al. (Google)  
  Fine-tunes a model on many tasks phrased as natural-language instructions, which improves zero-shot performance on new tasks. _Established instruction tuning, the supervised step before any preference tuning._
- [ ] **[Self-Instruct](https://arxiv.org/abs/2212.10560)** · Common · 2022  
  Self-Instruct: Aligning Language Models with Self-Generated Instructions · Yizhong Wang et al. (UW / AI2)  
  Bootstraps instruction data by having a model generate, filter and answer its own instructions from a small seed set. _Started LLM-generated instruction data and modern synthetic fine-tuning pipelines._
- [ ] **[Knowledge distillation](https://arxiv.org/abs/1503.02531)** · Standard · 2015  
  Distilling the Knowledge in a Neural Network · Geoffrey Hinton et al. (Google)  
  Trains a small student model to match a large teacher's softened outputs. _The foundation for today's small LLMs distilled from frontier teachers._
- [ ] **[On-policy distillation (GKD)](https://arxiv.org/abs/2306.13649)** · Emerging · 2023  
  On-Policy Distillation of Language Models: Learning from Self-Generated Mistakes · Rishabh Agarwal et al. (Google DeepMind)  
  The teacher scores text the student generates itself, rather than only teacher-written text. _A popular, cheap alternative to RL for post-training reasoning in 2025._
- [ ] **[Task arithmetic (model merging)](https://arxiv.org/abs/2212.04089)** · Common · 2022  
  Editing Models with Task Arithmetic · Gabriel Ilharco et al. (UW)  
  Task vectors (fine-tuned minus base weights) can be added, subtracted or combined to edit behavior. _The basis of model merging (TIES, DARE, mergekit), widely used to combine fine-tunes without retraining._
- [ ] **[Synthetic textbook data (phi-1)](https://arxiv.org/abs/2306.11644)** · Common · 2023  
  Textbooks Are All You Need · Suriya Gunasekar et al. (Microsoft Research)  
  A small code model trained on filtered web data plus LLM-written textbook-quality data beats much larger models. _Showed data quality and synthetic data can replace raw scale._
- [ ] **[RLVR (Tulu 3)](https://arxiv.org/abs/2411.15124)** · Standard · 2024  
  Tulu 3: Pushing Frontiers in Open Language Model Post-Training · Nathan Lambert et al. (AI2)  
  A fully open post-training recipe (SFT, DPO, then RL with verifiable rewards) that named RLVR. _Rewarding checkable answers instead of learned preferences is the core of 2025–26 reasoning and agent training._

### Architecture & scaling (18)

_Learned in Stage 5._

- [ ] **[Transformer](https://arxiv.org/abs/1706.03762)** · Standard · 2017  
  Attention Is All You Need · Ashish Vaswani et al. (Google)  
  An encoder-decoder model built only from self-attention and feed-forward layers, with no recurrence or convolution. _Almost every modern LLM, vision and speech model is built on it._
- [ ] **[BERT](https://arxiv.org/abs/1810.04805)** · Historical · 2018  
  BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding · Jacob Devlin et al. (Google)  
  Pre-trains a bidirectional Transformer encoder with masked-language modeling, then fine-tunes it for downstream tasks. _Encoder models like it still power the embeddings, rerankers and classifiers in RAG systems._
- [ ] **[Scaling laws (Kaplan)](https://arxiv.org/abs/2001.08361)** · Standard · 2020  
  Scaling Laws for Neural Language Models · Jared Kaplan et al. (OpenAI)  
  Language-model loss falls as a smooth power law in parameters, data and compute. _It turned model building into predictable compute planning and justified the scale race._
- [ ] **[Chinchilla (compute-optimal scaling)](https://arxiv.org/abs/2203.15556)** · Standard · 2022  
  Training Compute-Optimal Large Language Models · Jordan Hoffmann et al. (DeepMind)  
  For a fixed compute budget, parameters and training tokens should grow about equally, roughly 20 tokens per parameter. _It moved the field to smaller models trained on far more data. Today's models go further and over-train for cheaper inference._
- [ ] **[RoPE (rotary position embeddings)](https://arxiv.org/abs/2104.09864)** · Standard · 2021  
  RoFormer: Enhanced Transformer with Rotary Position Embedding · Jianlin Su et al.  
  Encodes position by rotating query and key vectors, so attention depends on relative distance. _The default position encoding in Llama, Qwen, Mistral, DeepSeek and most open models, and the basis of context-extension tricks._
- [ ] **[YaRN (long-context extension)](https://arxiv.org/abs/2309.00071)** · Common · 2023  
  YaRN: Efficient Context Window Extension of Large Language Models · Bowen Peng et al. (Nous Research / EleutherAI)  
  Rescales RoPE frequencies with a little fine-tuning so a model handles much longer contexts. _A widely used recipe for extending context windows to 128K and beyond cheaply._
- [ ] **[Grouped-query attention (GQA)](https://arxiv.org/abs/2305.13245)** · Standard · 2023  
  GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints · Joshua Ainslie et al. (Google)  
  Groups of query heads share key/value heads, sitting between full multi-head and multi-query attention. _It shrinks the KV cache and speeds up decoding with little quality loss, and is standard in most open models._
- [ ] **[Switch Transformer (sparse MoE)](https://arxiv.org/abs/2101.03961)** · Standard · 2021  
  Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity · William Fedus et al. (Google)  
  Simplifies mixture-of-experts by sending each token to a single expert, with a load-balancing loss. _It made sparse MoE practical, and MoE is now the dominant design for frontier and large open models._
- [ ] **[Mixtral (open MoE)](https://arxiv.org/abs/2401.04088)** · Common · 2024  
  Mixtral of Experts · Albert Q. Jiang et al. (Mistral AI)  
  An open sparse MoE with 8 experts and top-2 routing, using about 13B active out of 47B parameters. _Showed open MoE models can match much larger dense ones at lower inference cost._
- [ ] **[Mamba (state-space models)](https://arxiv.org/abs/2312.00752)** · Emerging · 2023  
  Mamba: Linear-Time Sequence Modeling with Selective State Spaces · Albert Gu & Tri Dao (CMU / Princeton)  
  A sequence model with input-dependent parameters that runs in linear time with a fixed-size state. _The main alternative to attention, now mostly used inside hybrid models for long-context efficiency._
- [ ] **[Llama 3](https://arxiv.org/abs/2407.21783)** · Standard · 2024  
  The Llama 3 Herd of Models · Aaron Grattafiori et al. (Meta)  
  A detailed report on pretraining, scaling, post-training and infrastructure for dense models from 8B to 405B. _The most complete public recipe for a frontier-class dense LLM._
- [ ] **[Multi-head Latent Attention (MLA)](https://arxiv.org/abs/2405.04434)** · Common · 2024  
  DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model · DeepSeek-AI  
  Compresses keys and values into a small shared latent vector, alongside the fine-grained DeepSeekMoE design. _Cuts the KV cache far more than GQA while keeping quality, and is spreading to other models._
- [ ] **[DeepSeek-V3](https://arxiv.org/abs/2412.19437)** · Standard · 2024  
  DeepSeek-V3 Technical Report · DeepSeek-AI  
  A 671B-total, 37B-active MoE combining MLA, auxiliary-loss-free load balancing, multi-token prediction and FP8 training. _Frontier-level quality at a fraction of the usual training cost, and the template for many 2025 open models._
- [ ] **[CLIP](https://arxiv.org/abs/2103.00020)** · Standard · 2021  
  Learning Transferable Visual Models From Natural Language Supervision · Alec Radford et al. (OpenAI)  
  Trains an image encoder and a text encoder together so images and captions share one embedding space. _CLIP-style encoders are the eyes of most multimodal LLMs and the basis of image search._
- [ ] **[Gated DeltaNet (hybrid linear attention)](https://arxiv.org/abs/2412.06464)** · Emerging · 2024  
  Gated Delta Networks: Improving Mamba2 with Delta Rule · Songlin Yang et al. (MIT / NVIDIA)  
  A linear-attention layer combining gating with the delta update rule for better memory control. _The main ingredient of 2025 hybrid models that mix linear and full attention, such as Qwen3-Next and Kimi Linear._
- [ ] **[Native Sparse Attention](https://arxiv.org/abs/2502.11089)** · Emerging · 2025  
  Native Sparse Attention: Hardware-Aligned and Natively Trainable Sparse Attention · Jingyang Yuan et al. (DeepSeek / Peking U.)  
  Trainable sparse attention with compressed, selected and sliding-window branches, designed to run fast on GPUs. _Started the move to learned sparse attention for long context, which DeepSeek shipped in V3.2._
- [ ] **[Gated attention](https://arxiv.org/abs/2505.06708)** · Emerging · 2025  
  Gated Attention for Large Language Models: Non-linearity, Sparsity, and Attention-Sink-Free · Zihan Qiu et al. (Qwen, Alibaba)  
  Adds a per-head sigmoid gate after attention, which removes attention sinks and stabilizes training. _A cheap tweak adopted in Qwen3-Next, representative of 2025 refinements to the attention block._
- [ ] **[Muon optimizer at scale](https://arxiv.org/abs/2502.16982)** · Emerging · 2025  
  Muon is Scalable for LLM Training · Jingyuan Liu et al. (Moonshot AI)  
  Scales the Muon optimizer, which orthogonalizes updates, to large LLM pretraining with about 2x the efficiency of AdamW. _The first serious challenger to AdamW at frontier scale, used to train Kimi K2._

### Inference & efficiency (10)

_Learned in Stage 9._

- [ ] **[FlashAttention](https://arxiv.org/abs/2205.14135)** · Standard · 2022  
  FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness · Tri Dao et al. (Stanford)  
  Computes exact attention in tiles held in fast on-chip memory, never writing the full attention matrix to GPU memory. _Made long contexts affordable and is built into every training and inference stack._ Also: [FlashAttention-2](https://arxiv.org/abs/2307.08691), [FlashAttention-3](https://arxiv.org/abs/2407.08608)
- [ ] **[PagedAttention (vLLM)](https://arxiv.org/abs/2309.06180)** · Standard · 2023  
  Efficient Memory Management for Large Language Model Serving with PagedAttention · Woosuk Kwon et al. (UC Berkeley)  
  Stores the KV cache in fixed-size blocks, like virtual-memory pages, removing fragmentation and allowing shared prefixes. _The basis of vLLM and high-throughput LLM serving._
- [ ] **[Continuous batching (Orca)](https://www.usenix.org/conference/osdi22/presentation/yu)** · Standard · 2022  
  Orca: A Distributed Serving System for Transformer-Based Generative Models · Gyeong-In Yu et al. (Seoul National U.)  
  Requests join and leave the batch at every decoding step instead of waiting for the whole batch to finish. _How every modern LLM server gets high GPU utilization. Published at OSDI 2022, not on arXiv._
- [ ] **[Speculative decoding](https://arxiv.org/abs/2211.17192)** · Standard · 2022  
  Fast Inference from Transformers via Speculative Decoding · Yaniv Leviathan et al. (Google)  
  A small draft model proposes several tokens and the large model checks them in one pass, giving identical outputs 2–3x faster. _Built into all major serving stacks, with variants such as EAGLE, Medusa and multi-token prediction._
- [ ] **[GPTQ](https://arxiv.org/abs/2210.17323)** · Standard · 2022  
  GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers · Elias Frantar et al. (IST Austria)  
  One-shot 3–4-bit weight quantization that corrects rounding errors layer by layer using second-order information. _Made 4-bit LLMs practical and is still a standard quantization format._
- [ ] **[AWQ](https://arxiv.org/abs/2306.00978)** · Standard · 2023  
  AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration · Ji Lin et al. (MIT)  
  Protects the small share of weight channels that matter most by scaling them before 4-bit quantization. _A widely used 4-bit format in vLLM, TensorRT-LLM and Hugging Face._
- [ ] **[LLM.int8() (bitsandbytes)](https://arxiv.org/abs/2208.07339)** · Common · 2022  
  LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale · Tim Dettmers et al. (UW / Meta)  
  8-bit inference that keeps rare large outlier features in 16-bit and quantizes everything else. _Found the outlier problem behind most later LLM quantization work, and powers bitsandbytes in Hugging Face._
- [ ] **[Attention sinks (StreamingLLM)](https://arxiv.org/abs/2309.17453)** · Common · 2023  
  Efficient Streaming Language Models with Attention Sinks · Guangxuan Xiao et al. (MIT / Meta)  
  Keeps the first few 'sink' tokens plus a sliding window of the KV cache, so models can stream indefinitely with a fixed-size cache. _Explained attention sinks and underpins KV-cache eviction methods in serving engines._
- [ ] **[KV-cache quantization (KIVI)](https://arxiv.org/abs/2402.02750)** · Emerging · 2024  
  KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache · Zirui Liu et al. (Rice / Texas A&M)  
  Quantizes the KV cache to 2 bits with no fine-tuning. _The KV cache is the memory bottleneck in long-context serving, and low-bit caches like this are now common._
- [ ] **[Prefix caching (SGLang RadixAttention)](https://arxiv.org/abs/2312.07104)** · Standard · 2023  
  SGLang: Efficient Execution of Structured Language Model Programs · Lianmin Zheng et al. (Stanford / UC Berkeley)  
  Keeps KV caches in a radix tree so shared prompt prefixes are reused automatically across requests. _The mechanism behind API prompt caching and big cost and latency savings for agents and RAG._

### Evaluation, safety & interpretability (28)

_Learned in Stages 2 and 9._

- [ ] **[LLM-as-a-judge (MT-Bench)](https://arxiv.org/abs/2306.05685)** · Standard · 2023  
  Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena · Lianmin Zheng et al. (LMSYS)  
  A strong LLM grades or compares other models' open-ended answers, and the paper measures how well those grades agree with humans. _The standard way to evaluate open-ended output at scale, with the judge's known biases (position, length, self-preference) documented._
- [ ] **[Chatbot Arena (human preference)](https://arxiv.org/abs/2403.04132)** · Standard · 2024  
  Chatbot Arena: An Open Platform for Evaluating LLMs by Human Preference · Wei-Lin Chiang et al. (LMSYS)  
  Crowdsourced blind A/B votes between two models are turned into Elo-style rankings. _The most cited public chat leaderboard, so you need to know how it works and where it breaks._
- [ ] **[The Leaderboard Illusion](https://arxiv.org/abs/2504.20879)** · Emerging · 2025  
  The Leaderboard Illusion · Shivalika Singh et al. (Cohere Labs)  
  Shows how private testing of many variants, selective disclosure and unequal data access distort arena rankings. _The main warning against reading leaderboard ranks as ground truth._
- [ ] **[HELM](https://arxiv.org/abs/2211.09110)** · Common · 2022  
  Holistic Evaluation of Language Models · Percy Liang et al. (Stanford CRFM)  
  Evaluates many models on shared scenarios and metrics: accuracy, calibration, robustness, fairness, toxicity and efficiency. _Made the case for multi-metric, transparent evaluation instead of single-number claims._
- [ ] **[MMLU](https://arxiv.org/abs/2009.03300)** · Historical · 2020  
  Measuring Massive Multitask Language Understanding · Dan Hendrycks et al. (UC Berkeley)  
  A multiple-choice benchmark across 57 subjects, from elementary to professional level. _The default capability headline for years and now saturated, a lesson in how benchmarks age._
- [ ] **[GSM8K (and verifiers)](https://arxiv.org/abs/2110.14168)** · Historical · 2021  
  Training Verifiers to Solve Math Word Problems · Karl Cobbe et al. (OpenAI)  
  8.5K grade-school math problems, introduced together with verifiers that rerank sampled solutions. _The canonical multi-step reasoning benchmark, and its verifier idea led to reward models and best-of-N._
- [ ] **[HumanEval and pass@k](https://arxiv.org/abs/2107.03374)** · Standard · 2021  
  Evaluating Large Language Models Trained on Code · Mark Chen et al. (OpenAI)  
  Introduced Codex, the HumanEval benchmark and the pass@k metric, which checks generated code against unit tests. _pass@k and test-based correctness are still the basic tools for evaluating code generation._
- [ ] **[SWE-Bench Pro](https://arxiv.org/abs/2509.16941)** · Emerging · 2025  
  SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks? · Xiang Deng et al. (Scale AI)  
  A harder, contamination-resistant successor to SWE-bench with long-horizon tasks from public and private repositories. _Labs moved to it as SWE-bench Verified saturated._
- [ ] **[GPQA](https://arxiv.org/abs/2311.12022)** · Standard · 2023  
  GPQA: A Graduate-Level Google-Proof Q&A Benchmark · David Rein et al. (NYU)  
  Expert-written biology, physics and chemistry questions that skilled non-experts can't answer even with web search. _GPQA Diamond is a standard headline number for frontier reasoning models._
- [ ] **[Humanity's Last Exam](https://arxiv.org/abs/2501.14249)** · Common · 2025  
  Humanity's Last Exam · Long Phan et al. (CAIS / Scale AI)  
  Very hard, expert-level questions across many fields, built to stay unsaturated as models improve. _A widely reported frontier benchmark._
- [ ] **[ARC-AGI](https://arxiv.org/abs/2505.11831)** · Common · 2025  
  ARC-AGI-2: A New Challenge for Frontier AI Reasoning Systems · François Chollet et al. (ARC Prize)  
  Abstract grid puzzles that test whether a model can learn a new skill from a few examples. _Measures fluid generalization rather than memorized knowledge. It follows Chollet's 2019 'On the Measure of Intelligence'._ Also: [On the Measure of Intelligence (2019)](https://arxiv.org/abs/1911.01547)
- [ ] **[BIG-bench](https://arxiv.org/abs/2206.04615)** · Historical · 2022  
  Beyond the Imitation Game: Quantifying and extrapolating the capabilities of language models · Aarohi Srivastava et al.  
  A collaborative suite of 200+ tasks for probing model capabilities and how they scale. _Shaped the debate on 'emergent' abilities and produced BIG-Bench Hard._
- [ ] **[TruthfulQA](https://arxiv.org/abs/2109.07958)** · Historical · 2021  
  TruthfulQA: Measuring How Models Mimic Human Falsehoods · Stephanie Lin et al. (Oxford / OpenAI)  
  Questions where repeating common human misconceptions gives a false answer. _Showed larger models can be less truthful, an early foundation for honesty evals._
- [ ] **[Detecting test-set contamination](https://arxiv.org/abs/2310.17623)** · Common · 2023  
  Proving Test Set Contamination in Black Box Language Models · Yonatan Oren et al. (Stanford)  
  A statistical test for whether a model saw a benchmark in training, using only log-probabilities. _Contamination can make scores meaningless, and this gives a principled check._
- [ ] **[LiveBench (fresh test sets)](https://arxiv.org/abs/2406.19314)** · Common · 2024  
  LiveBench: A Challenging, Contamination-Limited LLM Benchmark · Colin White et al. (Abacus.AI / NYU)  
  Regularly refreshes its questions from recent sources and grades them with objective answers, not LLM judges. _The practical answer to contamination: keep the test set newer than the training data._
- [ ] **[Indirect prompt injection](https://arxiv.org/abs/2302.12173)** · Standard · 2023  
  Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection · Kai Greshake et al. (CISPA)  
  Instructions hidden in retrieved content (web pages, emails, documents) can take over LLM apps and agents. _The founding threat model for securing RAG systems and tool-using agents._
- [ ] **[GCG adversarial jailbreaks](https://arxiv.org/abs/2307.15043)** · Common · 2023  
  Universal and Transferable Adversarial Attacks on Aligned Language Models · Andy Zou et al. (CMU)  
  A gradient-guided search finds adversarial suffixes that jailbreak aligned models and transfer to closed ones. _Showed safety training can be bypassed automatically, which drove robustness research._
- [ ] **[Automated red teaming](https://arxiv.org/abs/2202.03286)** · Standard · 2022  
  Red Teaming Language Models with Language Models · Ethan Perez et al. (DeepMind)  
  One model generates test inputs that make a target model misbehave, and a classifier flags the failures. _The template for the automated red teaming labs run before release._
- [ ] **[Human red teaming at scale](https://arxiv.org/abs/2209.07858)** · Common · 2022  
  Red Teaming Language Models to Reduce Harms: Methods, Scaling Behaviors, and Lessons Learned · Deep Ganguli et al. (Anthropic)  
  A study of manual red teaming across model sizes and safety methods, with a dataset of about 39K attacks. _The practical playbook and baseline data for human red-team programs._
- [ ] **[Transformer circuits framework](https://transformer-circuits.pub/2021/framework/index.html)** · Common · 2021  
  A Mathematical Framework for Transformer Circuits · Nelson Elhage et al. (Anthropic)  
  Breaks small attention-only transformers into interpretable paths through the residual stream and identifies induction heads. _The vocabulary (residual stream, QK/OV circuits) mechanistic interpretability is built on._
- [ ] **[Sparse autoencoders (Towards Monosemanticity)](https://transformer-circuits.pub/2023/monosemantic-features/index.html)** · Common · 2023  
  Towards Monosemanticity: Decomposing Language Models With Dictionary Learning · Trenton Bricken et al. (Anthropic)  
  Sparse autoencoders trained on activations recover interpretable features from neurons that each mix many concepts. _Made SAEs the main tool for finding features inside models._ Also: [Scaling Monosemanticity (2024)](https://transformer-circuits.pub/2024/scaling-monosemanticity/index.html)
- [ ] **[Circuit tracing (On the Biology of an LLM)](https://transformer-circuits.pub/2025/attribution-graphs/biology.html)** · Emerging · 2025  
  On the Biology of a Large Language Model · Jack Lindsey et al. (Anthropic)  
  Traces step-by-step computations such as planning and multi-hop reasoning inside a production model using attribution graphs. _Moves interpretability from lists of features to whole mechanisms._
- [ ] **[Sycophancy](https://arxiv.org/abs/2310.13548)** · Common · 2023  
  Towards Understanding Sycophancy in Language Models · Mrinank Sharma et al. (Anthropic)  
  RLHF assistants consistently tell users what they want to hear, partly because of human preference data. _A common, measurable failure that matters for every assistant product._
- [ ] **[Reward hacking and emergent misalignment](https://arxiv.org/abs/2511.18397)** · Emerging · 2025  
  Natural Emergent Misalignment from Reward Hacking in Production RL · Monte MacDiarmid et al. (Anthropic)  
  Models that learn to reward-hack in realistic RL coding environments generalize to broader misaligned behavior. _Reward hacking becomes a safety risk, not just a training nuisance, once RL is scaled up._
- [ ] **[Alignment faking](https://arxiv.org/abs/2412.14093)** · Emerging · 2024  
  Alignment faking in large language models · Ryan Greenblatt et al. (Anthropic / Redwood)  
  A model can comply selectively during training to avoid being modified, while behaving differently when unmonitored. _Shows behavioral evals can be gamed by the model being evaluated._
- [ ] **[METR task time horizons](https://arxiv.org/abs/2503.14499)** · Emerging · 2025  
  Measuring AI Ability to Complete Long Software Tasks · Thomas Kwa et al. (METR)  
  Measures how long a task (in human-expert time) agents can complete with 50% reliability, and finds it doubled about every 7 months. _The most cited single trend for agent capability._
- [ ] **[GDPval (real work evals)](https://arxiv.org/abs/2510.04374)** · Emerging · 2025  
  GDPval: Evaluating AI Model Performance on Real-World Economically Valuable Tasks · Tejal Patwardhan et al. (OpenAI)  
  Industry experts grade model deliverables on real tasks from 44 occupations against human professional work. _Marks the shift from academic quizzes to measuring real work output._
- [ ] **[Chain-of-thought monitoring](https://arxiv.org/abs/2507.11473)** · Emerging · 2025  
  Chain of Thought Monitorability: A New and Fragile Opportunity for AI Safety · Tomek Korbak et al. (multi-lab)  
  A cross-lab position paper arguing reasoning traces can be monitored for intent to misbehave, and that training pressure could destroy this. _Frames a key 2025–26 safety lever and the design choices that keep it usable._

## Certificates (only if you need the credential)

- [ ] **[IBM Generative AI Engineering Professional Certificate](https://www.coursera.org/professional-certificates/ibm-generative-ai-engineering)**  
  IBM · Certificate · 16 courses · ~150 h · Paid cert, courses audit free  
  From AI basics through Python, Flask, ML and Keras to transformers, LoRA, RLHF/DPO and RAG with LangChain. _Its useful courses already sit in Stages 2, 5, 6 and 7. Courses 1–2 are skipped and 4, 7, 8 and 9 repeat Ng. Pay for the certificate only if you need the credential._
- [ ] **[IBM AI Engineering Professional Certificate](https://www.coursera.org/professional-certificates/ai-engineer)**  
  IBM · Certificate · 13 courses · ~160 h · Paid  
  ML in sklearn, DL in Keras and PyTorch, transformers, fine-tuning, RAG and agents with LangChain. _Overlaps the IBM GenAI cert heavily and teaches both Keras and PyTorch. Don't take both IBM certs._
- [ ] **[Microsoft AI & ML Engineering Professional Certificate](https://www.coursera.org/professional-certificates/microsoft-ai-and-ml-engineering)**  
  Microsoft · Certificate · 5 courses · ~175 h · Paid + Azure  
  ML algorithms, DL, LLM troubleshooting agents, Azure ML, MLOps. _Only for Azure-focused jobs._
- [ ] **[Microsoft Generative AI Engineering Professional Certificate](https://www.coursera.org/professional-certificates/microsoft-generative-ai-engineering/)**  
  Microsoft · Certificate · 5 courses · ~96 h · Paid + Azure ($40–200)  
  Generative models, LLMs on Azure, RAG, multimodal, MLOps and responsible AI. _Only for Azure-focused jobs. Pick one Microsoft cert at most._
- [ ] **[More Applied Data Science with Python](https://www.coursera.org/specializations/more-applied-data-science-with-python)**  
  University of Michigan · Specialization · ~139 h · Paid  
  Data mining, unsupervised learning, network analysis, information extraction. _Data science and text mining, not AI engineering. Low priority._

## Skip list

Checked and left off the route.

| Link | What it is | Why skip |
|---|---|---|
| [Introduction to AI (Google AI Essentials, course 1)](https://www.coursera.org/learn/google-introduction-to-ai) | A 1.5-hour AI-literacy intro for using AI tools at work. | For end users, not builders. AI For Everyone covers it. |
| [LLM101n](https://github.com/karpathy/LLM101n) | A 17-chapter syllabus for 'Let's build a Storyteller'. | The course was never released and the repo is archived. Zero to Hero and LLMs-from-scratch cover the same syllabus with real content. |
| [get-shit-done](https://github.com/gsd-build/get-shit-done) | Spec-driven development and context engineering for Claude Code. | Archived in June 2026. Development continues as open-gsd/gsd-core. |
| [EnterpriseArchitecture](https://github.com/justinamiller/EnterpriseArchitecture) | A single README on enterprise-architecture layers, domains and maturity. | Unchanged since 2021 and lightly edited. The TOGAF course in Track B covers it properly. |
| [llmops-python-package](https://github.com/callmesora/llmops-python-package) | An LLMOps package template with MLflow, Bedrock RAG, Docker and CI. | Stale since February 2025 and built on Poetry. MLOps Zoomcamp and the Jam With AI project cover this better. |
| [Applied AI (glossary)](https://www.cognizant.com/us/en/glossary/applied-ai) | A short marketing definition with no technical content. | Marketing content with no technical depth. |
| [Getting Started with LLMs](https://www.linkedin.com/pulse/getting-started-llms-guide-resources-opportunities-wendy-ran-wei/) | A link roundup from April 2023. | Outdated and superseded by learn-ai-engineering. |
| [Introduction to Artificial Intelligence](https://www.coursera.org/learn/introduction-to-ai) | A non-technical overview of AI. | Repeats AI For Everyone. |
| [Generative AI: Introduction and Applications](https://www.coursera.org/learn/generative-ai-introduction-and-applications) | A tour of GenAI tools. | No engineering content, and it will date quickly. |
| [Intro to Deep Learning & Neural Networks with Keras](https://www.coursera.org/learn/introduction-to-deep-learning-with-keras) | Shallow Keras intro to NNs, CNNs and RNNs. | Much shallower than Ng's DL specialization, and it uses Keras while the rest of the route uses PyTorch. |
| [ML with Scikit-learn, PyTorch & HF (specialization URL)](https://www.coursera.org/specializations/machine-learning-scikit-learn-pytorch-hugging-face) | Serves the same program page as the professional certificate. | A duplicate of the certificate listed in Stage 3. |
| [IBM Introduction to Machine Learning Specialization](https://www.coursera.org/specializations/ibm-intro-machine-learning) | Four classical ML courses. | These are exactly the first 4 courses of the IBM ML Professional Certificate. |
| [Foundations of Deep Learning (Larochelle)](https://www.youtube.com/watch?v=zij_FTbJHsk&list=PLrAXtmErZgOfMuxkACrYnD2fTgbzk2THW&index=2) | A single 2016 lecture on feedforward nets and backprop. | The playlist ID no longer resolves, and Ng, MIT and fast.ai cover this better. |
| [Advanced_RAG](https://github.com/NisaarAgharia/Advanced_RAG) | Ten RAG notebooks. | Stale since April 2024. RAG_Techniques covers the same and more. |
| [RAGent](https://github.com/alonlavian/RAGent) | A small Streamlit PDF and web-search agent with 4 commits. | Inactive since December 2024, with no explanations. |
| [Rasa Open Source](https://github.com/RasaHQ/rasa) | Intent-based chatbot framework. | In maintenance mode. Rasa itself now points to its LLM-based CALM. |
| [Learn AI Agents](https://v2.scrimba.com/learn-ai-agents-c034) | JS agent course. | Already part of The AI Engineer Path. |
| [Intro to AI Engineering](https://v2.scrimba.com/intro-to-ai-engineering-c032) | JS LLM-app basics. | Already part of The AI Engineer Path. |
| [ML Artifacts (dictionary)](https://www.hopsworks.ai/dictionary/ml-artifacts) | About 200 words defining ML artifacts. | Vendor marketing. MLOps Zoomcamp teaches this properly. |
| [bitsandbytes cuda_install.sh](https://raw.githubusercontent.com/TimDettmers/bitsandbytes/main/cuda_install.sh) | A legacy CUDA install script. | Returns 404. Use pip install bitsandbytes instead (see Stage 6). |
| [500+ Python Interview Questions](https://applyre.com/resources/500-interview-questions/python/) | An interview Q&A page behind a job-application SaaS. | The content couldn't be verified, and it's not AI learning. |
| [Kling AI](https://klingai.com/) | Commercial AI video and image generator. | A tool to play with, not to learn from. |
| [Luma Dream Machine](https://lumalabs.ai/dream-machine?ref=FutureTools.io) | Commercial video and image generation, now sold as 'Luma Agents'. | A product, and it duplicates Kling. |
