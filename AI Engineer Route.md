# AI Engineer Route

A learning roadmap built from every link in your list, the DeepLearning.AI catalogue, three extra repos and your browser bookmarks. Every link was opened and checked in October 2026.

Online version with progress tracking: https://claude.ai/artifact/5KRkq84PEj5zvbtbBnqmzj

## How to read this

- **Do these**: the main path. **Alternatives** cover the same ground, so pick at most one. **Optional** adds depth. **Reference** is for lookups.
- **Builder track** (ship LLM apps, RAG and agents) skips Stages 4–6 and uses a lighter ML foundation: about **338 h** of core material, roughly 8 months at 10 h/week.
- **Full track** (also understand and train models) includes every stage: about **657 h**, roughly 15 months at 10 h/week.
- Items with a different role per track say so in italics. `added` marks gap-fillers that weren't in your list, and `bookmark` marks items from your browser bookmarks.
- In the online and HTML versions, click an item's circle to move it from Not started to In progress to Done. In this file, use `- [ ]` and `- [x]`, and add `🚧` after an item's title to mark it in progress.

## Stage 0: Orientation

~22 h of core material (Full track).

Get the vocabulary and a mental model of what LLMs are before you write code. You already finished AI For Everyone, so this stage is short.

### Do these

- [x] **[AI For Everyone](https://www.coursera.org/learn/ai-for-everyone/)**  
  DeepLearning.AI · Andrew Ng · Course · ~7 h · Audit free  
  Non-technical intro to what ML can do, AI projects and strategy. _You already completed this. It's from 2019, before generative AI._
- [ ] **[Generative AI for Everyone](https://www.coursera.org/learn/generative-ai-for-everyone)**  
  DeepLearning.AI · Andrew Ng · Course · ~6 h · Audit free  
  How LLMs work and where they fail; prompting, RAG and fine-tuning at a concept level; the GenAI project lifecycle. _The natural sequel to AI For Everyone. Take this instead of the Google AI cert and the IBM GenAI article._
- [ ] **[Neural networks series](https://www.youtube.com/watch?v=aircAruvnKk&list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi)**  
  3Blue1Brown · Video series · ~4 h · Free  
  Animated explanations of gradient descent, backprop, transformers, attention and how LLMs store facts. _The best intuition builder on the list. Chapters 5–7 (2024) cover transformers._
- [ ] **[Karpathy: Intro to LLMs and Deep Dive into LLMs](https://www.youtube.com/@AndrejKarpathy/videos)**  
  Andrej Karpathy · Talks · ~5 h · Free  
  Non-coding talks on how ChatGPT-style models are pretrained, fine-tuned and used. Start with the 1-hour 'Intro to Large Language Models', then the 3.5-hour 'Deep Dive into LLMs like ChatGPT' (2025). _The same channel hosts Zero to Hero, which is in Stage 5._

### Optional depth

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
- [ ] **[Essence of Linear Algebra](https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab)** `added`  
  3Blue1Brown · Video series · ~4 h · Free  
  Visual intuition for vectors, matrices, dot products and transforms, which is the math under every layer. _Added to cover the 'Mathematics for ML' item in your MISC notes._

### Alternatives (pick at most one)

- [ ] **[AI Python for Beginners](https://www.coursera.org/learn/ai-python-for-beginners)**  
  DeepLearning.AI · Andrew Ng · Course · ~20 h · Free on deeplearning.ai  
  Python from zero through small LLM-powered projects, with an AI tutor. _Gentler and more AI-flavoured than the Helsinki MOOC but shallower. Pick one._
- [ ] **[Python for Data Science, AI & Development](https://www.coursera.org/learn/python-for-applied-data-science-ai)**  
  IBM · Course · ~25 h · Audit free  
  Python basics, pandas, NumPy, REST APIs and scraping in Jupyter. _Course 4 of the IBM GenAI cert. Only needed if you don't know Python yet._
- [ ] **[Mathematics for Machine Learning](https://www.coursera.org/specializations/mathematics-machine-learning)** `added` _(Full track: alternative · Builder track: skip)_  
  Imperial College London · Specialization · ~60 h · Audit free  
  Linear algebra, multivariate calculus and PCA, aimed at ML. _Only needed on the Full track, if the math in Stages 4–6 feels shaky._

### Optional depth

- [ ] **[Data Analysis with Python](https://www.coursera.org/learn/data-analysis-with-python)**  
  IBM · Course · ~16 h · Audit free  
  Wrangling, EDA and regression with pandas and scikit-learn. _Good pandas practice. Its regression part repeats Ng's ML course 1._
- [ ] **[Mathematics for Machine Learning and Data Science](https://www.deeplearning.ai/specializations/mathematics-for-machine-learning-and-data-science)** _(Full track: optional · Builder track: skip)_  
  DeepLearning.AI · Luis Serrano · Specialization · ~94 h · DLAI Pro  
  Linear algebra, calculus, probability and statistics, with Python labs. _Friendlier than the Imperial specialization, which is now listed as its alternative. Only needed if the math in Stages 4–6 feels shaky._
- [ ] **[Automate the Boring Stuff with Python (3rd ed.)](https://automatetheboringstuff.com/)** `bookmark`  
  Al Sweigart · Free book · ~20 h · Free  
  Practical scripting: files, web scraping, spreadsheets and PDFs, scheduling, GUI automation. _Your bookmark pointed to the 2nd edition. The 3rd is current. Use it as a practical companion to the Helsinki MOOC._
- [ ] **[Software Design by Example](https://third-bit.com/sdxpy/intro/)** `bookmark`  
  Greg Wilson · Free book · ~30 h · Free  
  Learn design by building small versions of real tools: an interpreter, a test runner, a database, a web server. _From 2024. Nothing else on the route teaches software design, so read it after the MOOC to write better Python._
- [ ] **[Kaggle Learn](https://www.kaggle.com/learn)** `bookmark`  
  Kaggle · Micro-courses · ~8 h · Free  
  In-browser 3–5 hour courses: pandas, data cleaning, feature engineering, data viz, plus Google's self-paced GenAI and Agents intensives. _Do the pandas and feature-engineering ones before Stage 3. The ML and agent ones repeat what's on the route._

### Reference

- [ ] **[free-programming-books: Python courses](https://github.com/EbookFoundation/free-programming-books/blob/main/courses/free-courses-en.md#python)**  
  EbookFoundation · Link list · Free  
  About 50 free Python courses, including Django, Flask and FastAPI. _A directory, not a path. Use it to find alternatives._
- [ ] **[Comprehensive Python Cheatsheet](https://github.com/gto76/python-cheatsheet)** `bookmark`  
  gto76 · Reference · Free  
  The whole language on one page, and still maintained in 2026. _Keep it open while you code._
- [ ] **[Hypermodern Python](https://blog.claudiojolowicz.com/posts/hypermodern-python-01-setup/)** `bookmark`  
  Claudio Jolowicz · Article series · Free  
  A six-part guide to project setup, testing, linting, typing, docs and CI. _The ideas hold up, but the tools are from 2020. Use uv and ruff instead of Poetry, pyenv and flake8._
- [ ] **[Python Design Patterns and wtfpython](https://python-patterns.guide/)** `bookmark`  
  Brandon Rhodes · Satwik Kansal · Reference · Free  
  Idiomatic patterns for Python, plus a catalogue of surprising language gotchas with explanations. _Good for depth, not required._ Also: [wtfpython](https://github.com/satwikkansal/wtfpython)

**Build:** Write a script that pulls JSON from a public API, cleans it with pandas, and saves a chart and a CSV.

**Move on when:** You can write a small package with classes and tests without looking things up, and you can explain a matrix multiply.

## Stage 2: Build with LLM APIs

~26 h of core material (Full track).

Ship useful things on top of hosted models early: prompting, structured output, tool calls, embeddings. This keeps you motivated while the theory comes later.

### Do these

- [ ] **[Building software on top of LLMs (PyCon 2025)](https://building-with-llms-pycon-2025.readthedocs.io/en/latest/)**  
  Simon Willison · Workshop · ~4 h · Free (API costs)  
  Hands-on with the llm library: prompting from Python, text-to-SQL, structured extraction, embeddings/RAG, tool use and prompt injection. _The best practical first step on your list, and it takes about 3 hours._
- [ ] **[Anthropic courses](https://github.com/anthropics/courses)** `added`  
  Anthropic · Notebooks · ~8 h · Free (API costs)  
  Notebook courses on API fundamentals, prompt engineering, real-world prompting, prompt evaluations and tool use. _Added because it covers evals and tool use from a model provider's point of view._
- [ ] **[Prompt_Engineering](https://github.com/NirDiamant/Prompt_Engineering)**  
  Nir Diamant · Notebooks · ~12 h · Free  
  22 notebooks: zero/few-shot, chain-of-thought, self-consistency, decomposition, prompt security. _Active as of September 2026. Skim the basics and spend your time on the security and decomposition notebooks._
- [ ] **[Pydantic for LLM Workflows](https://www.deeplearning.ai/courses/pydantic-for-llm-workflows)**  
  DeepLearning.AI · Ryan Keenan · Short course · ~2 h · Free to watch  
  Validated structured outputs and tool-call data with Pydantic. _Exactly what the Stage 2 project needs, and it's vendor-neutral._

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
- [ ] **[Generative AI for Software Development](https://www.coursera.org/professional-certificates/generative-ai-for-software-development)**  
  DeepLearning.AI · Laurence Moroney · Certificate · ~34 h · Audit free  
  Using LLMs as a pair programmer: writing, testing, documenting code and AI-assisted design. _About productivity, not about building AI. Take it any time you like._
- [ ] **[Getting Structured LLM Output](https://www.deeplearning.ai/courses/getting-structured-llm-output)**  
  DeepLearning.AI × DotTxt · Short course · ~1.5 h · Free to watch  
  Covers JSON modes, re-prompting and constrained decoding with Outlines. _Explains how structured generation works under the hood._
- [ ] **[Safety system messages](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/system-message)** `bookmark`  
  Microsoft Learn · Docs · ~0.5 h · Free  
  How to write, iterate on and test system prompts, with their safety techniques and limits. _A short, mostly vendor-neutral checklist. Your bookmark's URL has moved, and this is the new one._

### Reference

- [ ] **[DeepLearning.AI short courses](https://learn.deeplearning.ai/my/learnings)**  
  DeepLearning.AI + partners · Course platform · ~8 h · Freemium  
  1–2 hour hands-on courses on prompting, RAG, agents, evals and fine-tuning, made with OpenAI, Anthropic, LangChain, Hugging Face and others. _Your dashboard. I went through the full catalogue of 131 items and placed the 25 worth taking in their stages. The rest are mostly thin partner showcases or superseded 2023–24 courses. Short courses are free to watch, while the longer courses and certificates need DeepLearning.AI Pro._
- [ ] **[Prompt Engineering Guide](https://www.promptingguide.ai/)**  
  DAIR.AI · Docs · Free  
  A full catalogue of prompting techniques, agents, context engineering and risks, with papers. _Kept current (2026). Use it as a lookup, not to read cover to cover._
- [ ] **[Artificial Analysis](https://artificialanalysis.ai/)** `bookmark`  
  Artificial Analysis · Leaderboard · Free  
  Independent comparison of models and API providers on intelligence, speed, latency and price. _Where to look when choosing a model for a project. Nothing else on the route covers this._
- [ ] **[OpenAI Cookbook](https://github.com/openai/openai-cookbook)** `bookmark`  
  OpenAI · Notebooks · Free (API costs)  
  Runnable examples for tool calling, structured outputs, embeddings, RAG, agents and evals. _The OpenAI counterpart to the Anthropic courses. Look things up here rather than working through it._

**Build:** Build a CLI that turns messy text (emails, invoices, logs) into validated JSON with Pydantic, and include an eval set of 20 examples.

**Move on when:** You can pick zero-shot, few-shot or chain-of-thought for a task, and you can explain a prompt injection risk in your own app.

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
- [ ] **[ML with Scikit-learn, PyTorch & Hugging Face](https://www.coursera.org/professional-certificates/machine-learning-scikit-learn-pytorch-hugging-face)**  
  Coursera · industry instructors · Certificate · ~137 h · Paid  
  Five courses: sklearn ML, advanced techniques, PyTorch DL, Hugging Face GenAI, end-to-end project. _A modern stack in one package that covers Stages 3–5 at a lighter depth. The instructors aren't named._

### Optional depth

- [ ] **[3 · Unsupervised Learning, Recommenders, RL](https://www.coursera.org/learn/unsupervised-learning-recommenders-reinforcement-learning)**  
  Andrew Ng · Course · ~28 h · Audit free  
  Clustering, anomaly detection, collaborative filtering, deep Q-learning. _Your list marked this 'OTHER'. It's useful but not on the critical path._
- [ ] **[ML From Scratch](https://www.python-engineer.com/courses/mlfromscratch/01_knn/)**  
  Python Engineer · Patrick Loeber · Video series · ~10 h · Free  
  Implements KNN, regression, Naive Bayes, SVM, trees, PCA and K-Means in NumPy. _The site returned 503 when I checked. The code is mirrored at github.com/patrickloeber/MLfromscratch._ Also: [GitHub mirror](https://github.com/patrickloeber/MLfromscratch)
- [ ] **[CS50's Introduction to AI with Python](https://pll.harvard.edu/course/cs50s-introduction-artificial-intelligence-python)**  
  Harvard · Malan & Yu · Course · ~70 h · Free  
  Project-heavy classical AI: search, logic, probability, optimization, ML, RL, neural nets, NLP. _Covers search and logic, which none of the ML certs do. It's weak on LLMs._
- [ ] **[Cynthia Rudin's channel](https://www.youtube.com/@cynthiarudinduke/videos)**  
  Duke · Cynthia Rudin · Talks · Free  
  Research talks on interpretable ML, plus lectures for her free textbook 'Intuition for the Algorithms of Machine Learning'. _For interpretability depth. It's not a course._
- [ ] **[mlcourse.ai](https://mlcourse.ai/book/index.html)** `bookmark`  
  Yury Kashnitsky · Course · ~40 h · Free  
  Ten topics of classic ML with assignments: trees, linear models, ensembles, gradient boosting, time series. _Only adds depth beyond Ng on boosting and time series._

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
    RNNs, LSTMs, word embeddings, attention, intro to transformers. _Your list marked this 'OTHER'. Keep it, because it is the bridge to Stage 5._
- [ ] **[MIT 6.S191: Introduction to Deep Learning](https://introtodeeplearning.com/)**  
  MIT · Amini & Amini · Course · ~20 h · Free  
  Fast bootcamp from fundamentals through generative models, RL and LLMs, with three code labs. _The 2026 edition is the most current deep learning course on your list._

### Alternatives (pick at most one)

- [ ] **[Practical Deep Learning for Coders](https://course.fast.ai/Lessons/lesson1.html)**  
  fast.ai · Jeremy Howard · Course · ~40 h · Free  
  Top-down and code-first: train real models from lesson 1, then learn how they work. Part 2 builds Stable Diffusion. _A practical alternative to Ng's DL specialization. It's from 2022 and centred on the fastai library. Your separate YouTube playlist link is the same course._ Also: [YouTube playlist](https://www.youtube.com/playlist?list=PLfYUBJiXbdtSvpQjSnJJ_PmDQB_VyT5iU)

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
- [ ] **[Neural Networks and Deep Learning](http://neuralnetworksanddeeplearning.com/)** `bookmark`  
  Michael Nielsen · Free book · ~15 h · Free  
  Derives backprop and builds an MNIST classifier in NumPy, explaining every step. _Very clear on intuition. The code is dated (last updated 2019), and Karpathy's micrograd covers the same ground._
- [ ] **[An overview of gradient descent optimization algorithms](https://www.ruder.io/optimizing-gradient-descent/)** `bookmark`  
  Sebastian Ruder · Article · ~1 h · Free  
  Momentum, Adagrad, RMSprop and Adam compared side by side. _Still the clearest single read on optimizers. It predates AdamW._

### Reference

- [ ] **[Dive into Deep Learning (D2L)](https://d2l.ai/index.html)**  
  Zhang, Lipton, Li, Smola · Book · Free  
  An interactive textbook where every section is a runnable notebook, from basics to transformers. _Use it as the textbook alongside whichever course you take._
- [ ] **[Deep Learning (Goodfellow, Bengio, Courville)](https://www.deeplearningbook.org/)** `bookmark`  
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
- [ ] **[LLM Visualization](https://bbycroft.net/llm)** `bookmark`  
  Brendan Bycroft · Interactive · ~1.5 h · Free  
  A 3D walk through every step of one token's inference in a small GPT, with GPT-2 and GPT-3 scale views. _Spend an hour on it between 3Blue1Brown and Karpathy. It works on the Builder track too._
- [ ] **[Hands-On Large Language Models](https://github.com/HandsOnLLM/Hands-On-Large-Language-Models)** `bookmark`  
  Jay Alammar & Maarten Grootendorst · Book + notebooks · ~20 h · Notebooks free, book paid  
  A very visual book: tokens, embeddings, transformer internals, classification, clustering, semantic search and fine-tuning. _Same authors as DeepLearning.AI's How Transformer LLMs Work. Its embedding and topic-modelling chapters are the parts the route lacks._
- [ ] **[ViT and CLIP papers](https://arxiv.org/abs/2010.11929)** `bookmark`  
  Google · OpenAI · Papers · ~3 h · Free  
  Vision Transformer (2020) and CLIP (2021), the foundations of today's multimodal models and image embeddings. _Read them when you move into multimodal work._ Also: [CLIP paper](https://arxiv.org/abs/2103.00020)

### Reference

- [ ] **[LLM Architecture Gallery](https://sebastianraschka.com/llm-architecture-gallery/)** `bookmark`  
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

- [ ] **[bitsandbytes installation docs](https://huggingface.co/docs/bitsandbytes/main/en/installation)** `added`  
  Hugging Face · Docs · Free  
  The current install path is pip install bitsandbytes (Python 3.10+, PyTorch 2.4+). Prebuilt wheels cover CUDA 11.8–13, ROCm, CPU and Apple Silicon. _Replaces the cuda_install.sh script in your PACKAGES notes, which now returns 404._
- [ ] **[deep-learning-pytorch-huggingface](https://github.com/philschmid/deep-learning-pytorch-huggingface)**  
  Philipp Schmid · Notebook cookbook · Free  
  Notebook recipes for fine-tuning, DPO, GRPO, quantization and FSDP/DeepSpeed training on the Hugging Face stack. _Not a course, and inactive since February 2025. Most notebooks pin old TRL/PEFT versions and old models (FLAN-T5, Llama 2, Falcon). Only the 2025 ones (fine-tune LLMs in 2025, DPO in 2025, mini-R1 GRPO) are worth running, and many need A100-class GPUs._
- [ ] **[LLM Course (Labonne)](https://github.com/mlabonne/llm-course)** `bookmark`  
  Maxime Labonne · Roadmap + notebooks · Free  
  A roadmap in three tracks (Fundamentals, Scientist, Engineer), plus Colab notebooks for fine-tuning, quantization and model merging. _Mostly links that overlap this route. Its notebooks are good practical references for Stage 6. You had it bookmarked twice (GitHub and the HF blog)._

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
- [ ] **[Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)** `bookmark`  
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
  Qdrant in Docker or in memory, collections, embeddings, filtered queries, web UI. _You starred this one. Check calls against the current Qdrant client, which renamed query to query_points. It's optional now because the Jam With AI project uses OpenSearch, so do this tutorial if you want Qdrant specifically._
- [ ] **[bRAG-langchain](https://github.com/bRAGAI/bRAG-langchain/)**  
  bRAGAI · Notebooks · ~8 h · Free  
  Five notebooks: multi-query, routing, RAPTOR, ColBERT, fusion and reranking. _Follows 'RAG From Scratch' closely, so it's redundant if you did that._
- [ ] **[MongoDB GenAI Showcase](https://github.com/mongodb-developer/GenAI-Showcase)**  
  MongoDB · Notebooks · Free  
  RAG and agent examples and workshops on Atlas vector search. _Only useful if MongoDB is your vector store._
- [ ] **[Advanced Retrieval for AI with Chroma](https://www.deeplearning.ai/courses/advanced-retrieval-for-ai)**  
  DeepLearning.AI × Chroma · Short course · ~1 h · Free to watch  
  Query expansion, cross-encoder reranking and embedding adapters. _The techniques carry over to any vector store._

### Reference

- [ ] **[Emerging LLM App Stack](https://github.com/a16z-infra/llm-app-stack)**  
  a16z · Link list · ~1 h · Free  
  Tools listed by layer: data pipelines, embeddings, vector DBs, orchestration, eval, hosting. _A good mental model, but the tool lists stopped in February 2024 and predate agents and MCP. You also bookmarked the companion article, which has the architecture diagram._ Also: [Companion article (bookmark)](https://a16z.com/emerging-architectures-for-llm-applications/)
- [ ] **[Vector Database Comparison](https://superlinked.com/vector-db-comparison)** `bookmark`  
  Superlinked · Comparison table · Free  
  About 47 vector DBs compared on features, pricing, performance and integrations. _Maintained (August 2026). Use it when picking a store beyond Qdrant or OpenSearch._
- [ ] **[sentence-transformers](https://github.com/huggingface/sentence-transformers)** `bookmark`  
  Hugging Face · Library · Free  
  The standard library for local embedding, retrieval and reranking models, and for fine-tuning them. _Moved from UKPLab to Hugging Face. Docs are at sbert.net. Read them as needed._

**Build:** Build a question-answering bot over your own docs (for example, your setup_scripts repo) using Qdrant, with an evaluation set scored by RAGAS or similar.

**Move on when:** You can show measured retrieval precision before and after a reranker.

## Stage 8: Agents

~88 h of core material (Full track).

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
- [ ] **[CMU 11-768: AI Agents (Fall 2026)](https://www.cmu-agents.com/#/schedule)** `bookmark` _(Full track: core · Builder track: optional)_  
  CMU · Graham Neubig & Daniel Fried · University course · ~40 h · Free materials  
  Build an agent harness from scratch on an open model, design multi-step evals, and train agents with SFT and RL. _The only item on the route that covers agent harness internals and RL for agents. The course is running now, so slides and videos are still being released. It's graduate level, so take it last in this stage._

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
- [ ] **[Claude Code: A Highly Agentic Coding Assistant](https://www.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant)**  
  DeepLearning.AI × Anthropic · Short course · ~2 h · Free to watch  
  Subagents, hooks, MCP and GitHub integration in a real agent harness. _Useful as a productivity tool and as a look inside a production agent._
- [ ] **[Multi-Agent Systems with CrewAI](https://www.deeplearning.ai/courses/design-develop-and-deploy-multi-agent-systems-with-crewai)**  
  DeepLearning.AI × CrewAI · Course · ~13 h · DLAI Pro  
  Multi-agent systems with tools, memory, guardrails and deployment. _Tied to CrewAI. Take it only if multi-agent work is your focus._
- [ ] **[A2A: The Agent2Agent Protocol](https://www.deeplearning.ai/courses/a2a-the-agent2agent-protocol)**  
  DeepLearning.AI × Google Cloud & IBM · Short course · ~1.5 h · Free to watch  
  Make agents built on different frameworks interoperate. _MCP connects agents to tools, and A2A connects agents to each other._
- [ ] **[Gemini Fullstack LangGraph Quickstart](https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart)** `bookmark`  
  Google Gemini · Template · ~3 h · Free (API key)  
  React frontend plus LangGraph backend for a research agent that searches, reflects and cites. _A clean full-stack template for your Stage 8 project. Swap Gemini for any model._
- [ ] **[AI Agents for Beginners](https://github.com/microsoft/ai-agents-for-beginners)** `bookmark`  
  Microsoft · Course (18 lessons) · ~15 h · Free  
  Agent design patterns, MCP and A2A, context engineering, memory and agent security, on the Microsoft Agent Framework. _Mostly overlaps the HF Agents course. Its context-engineering and memory lessons are the useful extra. You bookmarked the Bulgarian translation, which is in the repo's translations folder._
- [ ] **[ollama-playground](https://github.com/NarimanN2/ollama-playground)** `bookmark`  
  Nariman N. · Projects · Free  
  Small local-model projects: PDF and hybrid RAG, MCP agents, multi-agent supervisor and swarm, voice, vision. _Project ideas that run entirely on your machine._

**Build:** Build a research agent with web search, a code tool and an MCP server you wrote, and add traces you can inspect.

**Move on when:** You can explain why your agent failed on a task by reading its trace.

## Stage 9: Production: MLOps and LLMOps

~100 h of core material (Full track).

Deploy, monitor and iterate: experiment tracking, model registry, orchestration, CI/CD, observability, guardrails, cost and latency.

### Do these

- [ ] **[Machine Learning in Production](https://www.coursera.org/learn/introduction-to-machine-learning-in-production/)**  
  DeepLearning.AI · Andrew Ng · Course · ~12 h · Paid  
  The ML project lifecycle: scoping, deployment patterns, drift, error analysis, data-centric AI. _Conceptual. Take it before MLOps Zoomcamp._
- [ ] **[MLOps Zoomcamp](https://github.com/DataTalksClub/mlops-zoomcamp)**  
  DataTalks.Club · Course · ~60 h · Free  
  MLflow tracking and registry, Prefect orchestration, batch, web and stream deployment, Evidently, Grafana monitoring, CI/CD, Terraform. _No 2026 cohort, so it's self-paced. Covers MLflow from your MISC notes. Kubeflow isn't covered anywhere on your list._
- [ ] **[Agents Towards Production](https://github.com/NirDiamant/agents-towards-production)**  
  Nir Diamant · Notebooks · ~25 h · Free  
  Taking agents to production: memory, tool auth, guardrails, tracing, evaluation, Docker/GPU deployment. _Many tutorials are sponsored, so the stacks are vendor-specific. Learn the pattern and swap in the vendor you prefer._
- [ ] **[Evaluating AI Agents](https://www.deeplearning.ai/courses/evaluating-ai-agents)**  
  DeepLearning.AI × Arize · Short course · ~3 h · Free to watch  
  Tracing, component and trajectory evals, LLM-as-judge, and experiment-driven iteration. _The best evals course in the catalogue. Its ideas apply from Stage 2 onward._

### Optional depth

- [ ] **[Machine Learning Zoomcamp](https://github.com/DataTalksClub/machine-learning-zoomcamp)**  
  DataTalks.Club · Alexey Grigorev · Course · ~120 h · Free  
  Project-based ML engineering: sklearn, FastAPI + Docker deployment, trees, DL, serverless, Kubernetes. _Core if you want a classic ML-engineer job. The 2026 cohort started on 14 September and you can join late._
- [ ] **[Apache Airflow](https://github.com/apache/airflow)**  
  Apache · Framework · Free  
  Workflow orchestration with Python DAGs. Airflow 3.x is current. _Learn it from the official tutorial, not the repo. Only needed for data and ML pipeline work._
- [ ] **[DeepLearning.AI Data Engineering Professional Certificate](https://www.coursera.org/professional-certificates/data-engineering)**  
  DeepLearning.AI & AWS · Joe Reis · Certificate · ~106 h · Paid  
  Pipelines on AWS: ingestion, storage, modelling, Airflow, Spark, SQL, IaC. _An adjacent skill, not AI. Covers the SQL from your MISC notes._
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
- [ ] **[From MLOps to ML Systems with FTI Pipelines](https://www.hopsworks.ai/post/mlops-to-ml-systems-with-fti-pipelines)** `bookmark`  
  Hopsworks · Jim Dowling · Article · ~0.5 h · Free  
  Split any ML system into feature, training and inference pipelines, a simple mental model for architecture. _Read it alongside MLOps Zoomcamp._
- [ ] **[What is Inference?](https://theaiengineer.substack.com/p/what-is-inference)** `bookmark`  
  Paolo Perrone · The AI Engineer · Article · ~0.3 h · Free  
  Prefill versus decode, the KV cache, why output tokens cost more, and PagedAttention. _From August 2026. A good primer before the vLLM course._
- [ ] **[Made With ML](https://github.com/GokuMohandas/Made-With-ML)** `bookmark`  
  Goku Mohandas · Course · ~30 h · Free  
  Take a PyTorch model to production with Ray, MLflow, pytest and GitHub Actions CI/CD. _Overlaps MLOps Zoomcamp. Its extras are Ray-based scaling and stronger software-engineering discipline._
- [ ] **[Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)** `bookmark`  
  Google Cloud · Templates · Free (GCP billed)  
  Production agent templates with CI/CD, evaluation and observability built in. _Only if you deploy on GCP. Your bookmark pointed at its old location in the generative-ai repo._

### Reference

- [ ] **[ml-ops.org](https://ml-ops.org/)**  
  INNOQ · Docs · Free  
  MLOps principles, maturity levels, CRISP-ML(Q), testing and governance. _Conceptual, tool-agnostic, and older than LLMOps._

**Build:** Ship your Stage 7 or Stage 8 app with Docker, run its eval suite in CI, add tracing and monitoring, and write a cost-per-request report.

**Move on when:** A regression in your prompt or model gets caught by CI before users see it.

## Reference shelf

- [ ] **[AI Engineering From Scratch](https://github.com/rohitg00/ai-engineering-from-scratch)**  
  Rohit Ghumare · Curriculum · ~342 h · Free (MIT)  
  523 text-and-code lessons in 20 phases, from math to agents, MCP, production and safety. It's very current (2026) and updated daily. _Its phases map onto this route (P1→Stage 1, P2→3, P3→4, P7/P10→5, P10/P11→6, P11→7, P13–16→8, P17→9), but don't follow all 342 hours. It grew very fast and looks heavily AI-assisted, so quality varies by lesson. Use it to fill gaps (Agent Skills, coding agents, 2026 architectures) and as a second explanation, not as a replacement for Karpathy or Raschka._
- [ ] **[Become a Machine Learning Engineer](https://www.maxmynter.com/pages/blog/become-mle)** `bookmark`  
  Max Mynter · Roadmap post · Free  
  A second-opinion roadmap for software engineers, which recommends mostly the same resources as this route. _Reassurance that the route is sensible, and nothing more._
- [ ] **[Hugging Face Papers (formerly Papers with Code)](https://huggingface.co/papers/trending)** `bookmark`  
  Hugging Face · Paper feed · Free  
  Trending research papers with code links. _paperswithcode.com now redirects here, so update your bookmark._
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
| [Applied AI (glossary)](https://www.cognizant.com/us/en/glossary/applied-ai) | A short marketing definition with no technical content. | It appeared twice in your list. |
| [Getting Started with LLMs](https://www.linkedin.com/pulse/getting-started-llms-guide-resources-opportunities-wendy-ran-wei/) | A link roundup from April 2023. | Outdated and superseded by learn-ai-engineering. |
| [Introduction to Artificial Intelligence](https://www.coursera.org/learn/introduction-to-ai) | A non-technical overview of AI. | Repeats AI For Everyone, which you've done. |
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
