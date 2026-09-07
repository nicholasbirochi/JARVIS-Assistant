# Revisão da importação do currículo

## Currículo consolidado (resume.json)

```json
{
  "meta": {
    "schema_version": "2.0",
    "canonical_language": "pt-BR",
    "last_updated": null,
    "source_documents": [
      "Currículo - DataBase - Brasil ATS.docx",
      "Currículo - DataBase - International ATS.docx"
    ]
  },
  "personal_info": {
    "full_name": "Nicholas Birochi",
    "location": {
      "city": null,
      "state": null,
      "country": null
    },
    "phone": "(11) 95827-5250",
    "email": "nicholas.birochi@gmail.com",
    "links": {
      "linkedin": "linkedin.com/in/nicholasbirochi",
      "github": "github.com/nicholasbirochi",
      "portfolio": null,
      "other": []
    },
    "evidence": []
  },
  "summary": {
    "pt": "Estudante de Engenharia da Computação com experiência em análise de dados, automação e IA aplicada, além de projetos em Python, R, SQL, Power BI e Excel. Tenho sólidos conhecimentos em estatística e programação, com habilidade em traduzir análises técnicas em insights.",
    "en": "Computer Engineering student with experience in data analysis, automation, and applied AI, plus project development in Python, R, SQL, Power BI, and Excel. Strong knowledge of statistics and programming, with ability to translate technical analyses into actionable insights."
  },
  "skills": [],
  "experience": [
    {
      "id": "volkswagen",
      "title": {
        "pt": "Estagiário em Análise de Dados (Auditoria Especial)",
        "en": "Data Analysis Intern (Special Audit)"
      },
      "company": "Volkswagen",
      "location": "Brasil",
      "start_date": "2025-04",
      "end_date": "Atual",
      "is_current": false,
      "bullets_pt": [
        "Desenvolvimento e manutenção de dashboard analítico em produção (Python, Dash/Flask, SQL/SQLite) para indicadores de presença e clima organizacional (GPTW), com arquitetura MVC, cache e exportação automática de relatórios em PDF/JPG.",
        "Criação de rotinas em Python para detecção automatizada de irregularidades em bases de ponto e acesso, apoiando investigações da Auditoria Especial.",
        "Extração e tratamento de dados no SAP (módulos de compras e materiais) e construção de dashboards em Power BI para suporte às decisões da auditoria.",
        "Aplicação prática de Databricks em projeto de monitoramento e análise comportamental de dados corporativos, apoiando a identificação de padrões e possíveis desvios para processos de auditoria e investigação.",
        "Desenvolvimento de uma ferramenta interna de IA local (sem uso de APIs externas) para apoiar a elaboração de relatórios de auditoria, automatizando parte do trabalho documental inicial.",
        "Colaboração com equipes para resolver problemas de dados e implementar soluções práticas."
      ],
      "bullets_en": [
        "Built and maintain a production analytics dashboard (Python, Dash/Flask, SQL/SQLite) for workforce presence and engagement (GPTW) reporting, with an MVC architecture, caching layer, and automated PDF/JPG exports.",
        "Built Python routines to automatically flag irregularities in timekeeping and access-control data, supporting Special Audit investigations.",
        "Extracted and processed SAP data (procurement/materials modules) and built Power BI dashboards to support audit decision-making.",
        "Applied Databricks in a corporate behavioral-monitoring and data-analysis project, supporting pattern identification and anomaly detection for audit and investigation processes.",
        "Built an internal, fully local AI tool (no external APIs) to help draft audit reports, automating part of the initial documentation work.",
        "Collaboration with teams to solve data issues and implement practical solutions."
      ],
      "evidence": []
    },
    {
      "id": "pratikaud",
      "title": {
        "pt": "Estagiário em Análise de Dados",
        "en": "Data Analysis Intern"
      },
      "company": "PratikaUD",
      "location": "Brasil",
      "start_date": "2023-01",
      "end_date": "2024-12",
      "is_current": false,
      "bullets_pt": [
        "Automatização e análise de dados utilizando funções avançadas do Excel, como PROCV, ÍNDICE e tabelas dinâmicas.",
        "Contribuição para a melhoria da eficiência dos processos de dados, resultando em um aumento de 45% na precisão de relatórios internos."
      ],
      "bullets_en": [
        "Automation and data analysis using advanced Excel functions such as VLOOKUP, INDEX, and pivot tables.",
        "Contributed to improved data process efficiency, resulting in a 45% increase in accuracy of internal reports."
      ],
      "evidence": []
    }
  ],
  "education": [
    {
      "degree": {
        "pt": "Engenharia da Computação",
        "en": "Computer Engineering"
      },
      "institution": "Faculdade Engenheiro Salvador Arena",
      "location": "Brasil",
      "status": "completed",
      "start_date": "2022-10",
      "end_date": "2027-12",
      "evidence": [
        {
          "source_path": "8º semestre – Período noturno – Formação prevista dez/2027",
          "source_type": "manual",
          "read_at": "2025-12",
          "snippet": null,
          "confidence": 1.0,
          "review_status": "pending"
        }
      ]
    },
    {
      "degree": {
        "pt": "Ensino Médio",
        "en": "High School"
      },
      "institution": "Colégio Ábaco",
      "location": "Brasil",
      "status": "completed",
      "start_date": "2022-10",
      "end_date": "2022-12",
      "evidence": [
        {
          "source_path": "Concluído em dez/2022",
          "source_type": "manual",
          "read_at": "2022-12",
          "snippet": null,
          "confidence": 1.0,
          "review_status": "pending"
        }
      ]
    }
  ],
  "projects": [],
  "certifications": [],
  "languages": [
    {
      "name": "Português",
      "proficiency": "Native",
      "test_score": null,
      "evidence": []
    },
    {
      "name": "Inglês",
      "proficiency": "Upper-Intermediate (B2 First, Score 153)",
      "test_score": null,
      "evidence": []
    },
    {
      "name": "Alemão",
      "proficiency": "Beginner (A1)",
      "test_score": null,
      "evidence": []
    }
  ],
  "job_preferences": {
    "target_roles": [
      "Analista de Dados Júnior"
    ],
    "notes": null,
    "availability": {
      "status": "unspecified",
      "notice_period_days": null,
      "available_from": null,
      "notes": null
    }
  },
  "conflicts": [
    {
      "id": "data_analysis",
      "field_path": "education",
      "existing_value": null,
      "proposed_value": null,
      "sources": [],
      "detected_at": "2023-10",
      "status": "resolved_manual",
      "resolution_note": null
    }
  ],
  "change_log": [
    {
      "timestamp": "2023-10-15",
      "field_path": "education",
      "old_value": "8º semestre – Período noturno – Formação prevista dez/2027",
      "new_value": "8º semestre – Período noturno – Formação prevista dez/2027",
      "source": "manual_review",
      "note": null
    }
  ]
}
```

## Fonte: Currículo - DataBase - Brasil ATS.docx

```
Nicholas Birochi — Estudante de Engenharia da Computação
(11) 95827-5250 | nicholas.birochi@gmail.com | linkedin.com/in/nicholasbirochi | github.com/nicholasbirochi
Objetivo
Analista de Dados Júnior.
Resumo Profissional
Estudante de Engenharia da Computação com experiência em análise de dados, automação e IA aplicada, além de projetos em Python, R, SQL, Power BI e Excel. Tenho sólidos conhecimentos em estatística e programação, com habilidade em traduzir análises técnicas em insights.
Experiência Profissional
Volkswagen — Estagiário em Análise de Dados (Auditoria Especial)
Abr/2025 – Atual
Desenvolvimento e manutenção de dashboard analítico em produção (Python, Dash/Flask, SQL/SQLite) para indicadores de presença e clima organizacional (GPTW), com arquitetura MVC, cache e exportação automática de relatórios em PDF/JPG.
Criação de rotinas em Python para detecção automatizada de irregularidades em bases de ponto e acesso, apoiando investigações da Auditoria Especial.
Extração e tratamento de dados no SAP (módulos de compras e materiais) e construção de dashboards em Power BI para suporte às decisões da auditoria.
Aplicação prática de Databricks em projeto de monitoramento e análise comportamental de dados corporativos, apoiando a identificação de padrões e possíveis desvios para processos de auditoria e investigação.
Desenvolvimento de uma ferramenta interna de IA local (sem uso de APIs externas) para apoiar a elaboração de relatórios de auditoria, automatizando parte do trabalho documental inicial.
Colaboração com equipes para resolver problemas de dados e implementar soluções práticas.
PratikaUD — Estagiário em Análise de Dados
Jan/2023 – Dez/2024
Automatização e análise de dados utilizando funções avançadas do Excel, como PROCV, ÍNDICE e tabelas dinâmicas.
Contribuição para a melhoria da eficiência dos processos de dados, resultando em um aumento de 45% na precisão de relatórios internos.
Formação
Engenharia da Computação — Faculdade Engenheiro Salvador Arena (8º semestre – Período noturno – Formação prevista dez/2027)
Ensino Médio — Colégio Ábaco (concluído em dez/2022)
Linguagens de Programação e Ferramentas
Python, R, SQL, C#, Java, Power BI, SAP, Excel (VBA), PowerApps, Power Automate, n8n, Dash/Flask, Azure (AZ-900), Databricks, Git
Idiomas
Inglês (Intermediário-Avançado – B2 First, Score 153)
Cambridge English Entry Level Certificate 2023 (B2 First – Score 153)
Access International School – Avançado
Português (Nativo)
Alemão: Iniciante (A1)
Projetos
Em R, Análise e Ciência de Dados:
Projeto e lições aprendidas no curso de R
Classificação de Fraude em Transações Bancárias (Árvore de Decisão)
Análise de Churn SaaS (TechGrow)
EDA e Limpeza de Dados (Tech Store / DataClean)
Projetos finais do curso de Power BI
Assistente de IA Local com Automação (n8n + Ollama)
Em C# e Java:
Projeto de Simulação de Áudio com Efeito Doppler
Projeto de Lançamento Balístico e Sistemas Lineares
Projeto de Criptografia (Matrix)
Cursos e Conquistas
Formação Plena em Análise e Ciência de Dados (em andamento – módulos concluídos de Machine Learning: regressão, classificação, clusterização, PCA/t-SNE, Random Forest, CatBoost e LightGBM)
Clean Code com Python (13h, Set/2025)
Módulos em Python, R, estatística e modelagem de dados
Curso de Linguagem R (7,5h, Dez/2024)
Aprofundamento em Probabilidade e Estatística (3h, Dez/2024)
Ciência de Dados para Iniciantes + Projetos Reais (4,5h, Ago/2024)
Análise de Dados em Python e Machine Learning (5h, Ago/2024)
Power BI (Eletiva, 40h, Faculdade, 2024)
SAP: Treinamento para Iniciantes, Financial Accounting e módulos MM/PP/FI/CO
Microsoft Azure Fundamentals (AZ-900)
Git Completo – Do Básico ao Avançado
Microsoft Power Apps – Essencial
Curso de Cabo - Monitoria no Tiro de Guerra 02-078 (Conclusão: Novembro/2024) – Treinamento em liderança e gerenciamento de equipes
Automação e IA: Power Automate (SharePoint), n8n (Automação e Agentes de IA), e Prompt Engineering
Segurança da Informação e Cibersegurança – Fundamentos
2026 VW SAM Region Internal Audit Workshop – Volkswagen do Brasil
Databricks — aplicado em projeto real de monitoramento e análise comportamental na Volkswagen
Comunicação
Liderança em projetos acadêmicos e cursos, como no desenvolvimento de dashboards em Power BI.
Experiência como monitor no Tiro de Guerra, promovendo colaboração e gestão de equipes.
Capacidade de traduzir análises técnicas em insights acionáveis para públicos não técnicos.
Desenvolvimento de uma solução de IA local para apoiar auditores, traduzindo resultados técnicos de forma clara para públicos não técnicos.
```

## Fonte: Currículo - DataBase - International ATS.docx

```
Nicholas Birochi — Computer Engineering Student
(11) 95827-5250 | nicholas.birochi@gmail.com | linkedin.com/in/nicholasbirochi | github.com/nicholasbirochi
Objective
Junior Data Analyst
Professional Summary
Computer Engineering student with experience in data analysis, automation, and applied AI, plus project development in Python, R, SQL, Power BI, and Excel. Strong knowledge of statistics and programming, with ability to translate technical analyses into actionable insights.
Professional Experience
Volkswagen — Data Analysis Intern (Special Audit)
Apr/2025 – Present
Built and maintain a production analytics dashboard (Python, Dash/Flask, SQL/SQLite) for workforce presence and engagement (GPTW) reporting, with an MVC architecture, caching layer, and automated PDF/JPG exports.
Built Python routines to automatically flag irregularities in timekeeping and access-control data, supporting Special Audit investigations.
Extracted and processed SAP data (procurement/materials modules) and built Power BI dashboards to support audit decision-making.
Applied Databricks in a corporate behavioral-monitoring and data-analysis project, supporting pattern identification and anomaly detection for audit and investigation processes.
Built an internal, fully local AI tool (no external APIs) to help draft audit reports, automating part of the initial documentation work.
Collaboration with teams to solve data issues and implement practical solutions.
PratikaUD — Data Analysis Intern
Jan/2023 – Dec/2024
Automation and data analysis using advanced Excel functions such as VLOOKUP, INDEX, and pivot tables.
Contributed to improved data process efficiency, resulting in a 45% increase in accuracy of internal reports.
Education
Computer Engineering — Engenheiro Salvador Arena College (8th semester – Evening program – Expected graduation Dec/2027)
High School — Colégio Ábaco (Completed Dec/2022)
Programming Languages & Tools
Python, R, SQL, C#, Java, Power BI, SAP, Excel (VBA), PowerApps, Power Automate, n8n, Dash/Flask, Azure (AZ-900), Databricks, Git
Languages
English (Upper-Intermediate – B2 First, Score 153)
Cambridge English Entry Level Certificate 2023 (B2 First – Score 153)
Access International School – Advanced
Portuguese (Native)
German: Beginner (A1)
Projects
In R, Data Analysis and Data Science:
Project and lessons learned in R course
Bank Transaction Fraud Classification (Decision Tree)
SaaS Churn Analysis (TechGrow)
EDA & Data Cleaning (Tech Store / DataClean)
Final projects from the Power BI course
Local AI Automation Assistant (n8n + Ollama)
In C# and Java:
Audio Simulation Project with Doppler Effect
Ballistic Launch and Linear Systems Project
Cryptography Project (Matrix)
Courses & Achievements
Comprehensive Training in Data Analysis and Data Science (ongoing – completed modules include Machine Learning: regression, classification, clustering, PCA/t-SNE, Random Forest, CatBoost, and LightGBM)
Clean Code with Python (13h, Sep/2025)
Modules in Python, R, statistics, and data modeling
R Programming Course (7.5h, Dec/2024)
Advanced Probability and Statistics (3h, Dec/2024)
Data Science for Beginners + Real Projects (4.5h, Aug/2024)
Data Analysis in Python and Machine Learning (5h, Aug/2024)
Power BI (Elective, 40h, College, 2024)
SAP: Beginner Training, Financial Accounting, and MM/PP/FI/CO modules
Microsoft Azure Fundamentals (AZ-900)
Git Complete – Basics to Advanced
Microsoft Power Apps – Essentials
Military Training Course – Monitoring at Tiro de Guerra 02-078 (Completed Nov/2024) – Leadership and team management training
Automation & AI: Power Automate (SharePoint), n8n (Automation and AI Agents), and Prompt Engineering
Information Security & Cybersecurity – Fundamentals
2026 VW SAM Region Internal Audit Workshop – Volkswagen do Brasil
Databricks — applied in a real behavioral-monitoring and data-analysis project at Volkswagen
Communication
Leadership in academic projects and courses, such as developing dashboards in Power BI.
Experience as a monitor at Tiro de Guerra, promoting collaboration and team management.
Ability to translate technical analyses into actionable insights for non-technical audiences.
Built a local AI tool to support auditors, translating technical results clearly for non-technical audiences.
```
