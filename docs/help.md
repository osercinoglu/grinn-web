# i-gRINN Documentation

## 1. Introduction

i-gRINN (**i**nteraction platform for (**g**et) **R**esidue **I**nteraction E**n**ergies and **N**etworks) is a freely available, web-based tool for analysis of biomolecular dynamics simulations based on **non-bonded residue interaction energy calculations**. The tool is a web port of [gRINN](https://www.github.com/osercinoglu/grinn) tool, which is essentially a containerized wrapper around [gromacs](https://manual.gromacs.org)' mdrun -rerun. i-gRINN provides a web-based service with an interactive interface for running gRINN analysis on user-uploaded gromacs trajectory data or PDB conformational ensembles, with built-in visualization through an interactive dashboard.

This website is free and open to all users and there is no login requirement.
No cookies are stored.

### 1.1 Main Capabilities and Features

- **Pairwise Non-bonded Residue Interaction Energy Calculation**: Compute non-bonded interaction (van der Waals and Electrostatic) energies between all potential or selected residue pairs across input simulation trajectory frames or conformational ensembles in PDB format.
- **Protein Energy Networks**: Construct and analyze interaction energy based residue interaction networks (RINs), i.e. Protein Energy Networks (PENs) with node centrality metrics and shortest paths to identify functionally important residues and allosteric communication pathways, respectively.
- **Interactive Dashboard**: Visualize analysis results using a rich and interactive dashboard interface with integrated molecular ([Mol*](https://molstar.org/)) and network viewers ([3D-force-directed graph](https://github.com/vasturiano/3d-force-graph)).
- **Chat with Data**: Chat with popular large language models (LLMs) including Gemini Pro and Claude Sonnet 4 to explore result dataframes via pandasai and LiteLLM. 
- **Two Analysis Modes**: Support for both gromacs-generated biomolecular dynamics trajectories (XTC/TRR) and topologies as well as custom PDB conformational ensembles.
- **Residue-agnostic Analysis**: Support for _any_ residue type provided that it is properly defined in input .itp/.top files (only available from gromacs trajectories).

### 1.2 Use Cases

- **Residue-level analysis of biomolecular conformational ensembles**: Identify the functional importance of residues in the context of overall molecular dynamics and stability.  
- **Mutation Impact**: Understand the effect of mutations on intramolecular communication.
- **Allosteric Communication**: Identify energy pathways that transmit signals between distant protein sites.
- **Binding Site Analysis for Drug Design**: Characterize residue interactions at ligand binding sites.
- **Conformational Dynamics**: Compare energy patterns across different conformational states

---

## 2. Getting Started

To use i-gRINN:

1. **Select Analysis Mode**: Choose between Trajectory Mode (for MD simulations) or Ensemble Mode (for PDB conformational ensembles)
2. **Upload Files**: Provide the required input files for your selected mode
3. **Configure Parameters**: Adjust analysis parameters as needed (optional)
4. **Submit Job**: Click "Submit Job" to start the analysis
5. **Monitor Progress**: Track your job in the Job Queue
6. **Explore Results**: Launch the interactive dashboard when analysis completes

### 2.1 Quick Example

Use the **Load Example Trajectory/Ensemble Data** button to quickly load sample data and test the analysis workflow.

---

## 3. Input Data

i-gRINN supports two analysis modes with different input requirements:

### 3.1 Trajectory Mode

For analyzing molecular dynamics simulation trajectories generated with GROMACS:

**Required Files:**

| File Type    |  Extensions      | Description            |
|--------------|------------------|------------------------|
| Structure    | `.pdb`           | Protein structure file |
| Trajectory   | `.xtc` or `.trr` | MD trajectory file     |
| Topology     | `.top`           | GROMACS topology file  |

**Optional Files:**

- `.itp` files: Include topology files (force field parameters)
- `.zip` files: Compressed force field folders

### 3.2 Ensemble Mode

For analyzing conformational ensembles stored in multi-model PDB files.

**Required Files:**

| File Type | Extensions | Description |
|-----------|------------|-------------|
| Ensemble PDB | `.pdb` | Multi-model PDB file with MODEL/ENDMDL records |

The PDB file should contain multiple conformations separated by `MODEL` and `ENDMDL` records. Each model represents a different conformational state of the protein.

### 3.3 File Size Limits

- **Trajectory/Multi-model PDB files** (XTC/TRR in trajectory mode, PDB in ensemble mode): Up to 100 MB
- **Structure/topology files**: Up to 10 MB
- **Frame/model number**: Up to 200

---

## 4. Running Analysis

### 4.1 Analysis Parameters

Configure the following parameters before submitting your job:

| Parameter | Default | Description |
|-----------|---------|-------------|
| **GROMACS Version** | 2024.1 | GROMACS version for energy calculations |

### 4.2 Advanced Parameters

Click "Advanced Parameters" to customize:

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Skip Frames** | 1 | Analyze every Nth frame (1 = all frames, 2 = every other frame) |
| **Initial Pair Filter Cutoff** | 12.0 Å | Maximum distance for initial residue pair selection. Only residue pairs whose centers of mass are within this cutoff distance with each other will be included in the calculation. |
| **Source Selection** | (all) | [ProDy selection](http://www.bahargroup.org/prody/manual/reference/atomic/select.html#selections) for source residues |
| **Target Selection** | (all) | [ProDy selection](http://www.bahargroup.org/prody/manual/reference/atomic/select.html#selections) for target residues |

### 4.3 Job Submission

- Ensure all required files are uploaded (you will see a **Ready to Submit** message right below the **Submit Job** button).
- Click **Submit Job** to queue the analysis.
- You will receive a Job ID and a **Monitor** link to view info about the status of the job.

---

## 5. Methodology

### 5.1 Pairwise Residue Interaction Energy Calculation

i-gRINN calculates **non-bonded pairwise residue interaction energies** between all residue pairs in a protein structure across trajectory frames or conformational ensemble models. The calculation uses GROMACS's `mdrun -rerun` functionality to re-evaluate energies from existing coordinates.

#### 5.1.1 Energy Components

For each pair of residues (i, j), three energy components are computed:

| Component | Description |
|-----------|-------------|
| **Van der Waals (VdW)** | Lennard-Jones potential interactions |
| **Electrostatic (Elec)** | Coulombic interactions between partial atomic charges |
| **Total** | Sum of VdW and Electrostatic components |

#### 5.1.2 Calculation Workflow

1. **Initial Pair Filtering**: To reduce computational cost, only residue pairs whose centers of mass come within the specified cutoff distance (default: 12 Å) are included in the calculation.

2. **Energy Group Definition**: Each residue is defined as a separate energy group in GROMACS.

3. **Trajectory Re-evaluation**: GROMACS `mdrun -rerun` recalculates non-bonded energies for each frame using the force field parameters from the topology file.

4. **Energy Extraction**: Pairwise energies are extracted from GROMACS energy files (.edr) and organized into per-frame matrices.

> **Note**: All energies are reported in **kcal/mol** (converted from GROMACS's native kJ/mol).

### 5.2 Protein Energy Networks (PENs)

Protein Energy Networks are graph-based representations of residue interactions, first introduced by Vijayabaskar and Vishveshwara [[VV2010](#references)]. In PENs, residues are represented as **nodes** and significant interactions as **edges**.

#### 5.2.1 Network Construction

1. **Nodes**: Each residue in the selected region becomes a node, identified by its residue name, number, and chain (e.g., `GLY290_A`).

2. **Edge Addition**: An edge is added between residues i and j if the absolute value of their interaction energy exceeds the specified cutoff (default: 1 kcal/mol).

3. **Edge Weights**: Edge weights (ω) are assigned based on interaction strength, favoring attractive (negative) interactions:

```
ω_ij = 0.99                        (if i and j are covalently bound)
     = χ_ij                        (otherwise)
```

Where χ (chi) is computed as:

```
χ_ij = |ε_ij| / max|ε_att|         (if ε_ij < 0, i.e., attractive)
     = 0                           (otherwise)
```

Here, **ε_ij** is the average interaction energy between residues i and j, and **ε_att** represents all attractive (negative) energies. This normalization produces weights in the range [0, 0.99].

4. **Distance Property**: For path-finding algorithms, each edge is assigned a distance value: **d_ij = 1 − ω_ij**

#### 5.2.2 Covalent Bond Handling

PENs can optionally include or exclude covalent bonds (peptide bonds between sequence-adjacent residues). Including covalent bonds ensures network connectivity along the backbone; excluding them focuses analysis on non-covalent, potentially long-range interactions.

### 5.3 Network Analysis Metrics

i-gRINN computes several node-level (residue-level) centrality metrics to assess the structural and functional importance of each residue:

#### 5.3.1 Degree Centrality

The **degree** of a node is the number of edges connected to it. Residues with high degree are interaction "hubs" with many significant contacts.

#### 5.3.2 Betweenness Centrality

**Betweenness centrality** measures how often a node lies on the shortest paths between other nodes:

```
BC(v) = Σ [ σ_st(v) / σ_st ]    for all s ≠ v ≠ t
```

Where **σ_st** is the total number of shortest paths from node s to t, and **σ_st(v)** is the number of those paths passing through v. Residues with high betweenness centrality are critical for communication between distant protein regions and may be involved in allosteric signaling [[RO2014](#references)].

#### 5.3.3 Closeness Centrality

**Closeness centrality** measures how close a node is to all other nodes:

```
CC(v) = (n - 1) / Σ d(v, u)     for all u ≠ v
```

Where **d(v, u)** is the shortest path distance from v to u and **n** is the number of nodes. Residues with high closeness can efficiently communicate with the entire protein structure.

### 5.4 Shortest Path Analysis

i-gRINN identifies **shortest paths** between user-selected residue pairs using Dijkstra's algorithm [[DEW1959](#references)]. Since the algorithm favors lower-weight edges while stronger interactions should be preferred, the **distance** property **(1 − ω)** is used as the edge weight for pathfinding.

Shortest paths reveal potential **energy transmission pathways** that may mediate allosteric communication between distant functional sites.

### 5.5 References

| ID | Reference |
|----|-----------|
| **[VV2010]** | Vijayabaskar, M. S., & Vishveshwara, S. (2010). Interaction Energy Based Protein Structure Networks. *Biophysical Journal*, 99(11), 3704–3715. https://doi.org/10.1016/j.bpj.2010.08.079 |
| **[RO2014]** | Ribeiro, A. A. S. T., & Ortiz, V. (2014). Determination of Signaling Pathways in Proteins through Network Theory: Importance of the Topology. *Journal of Chemical Theory and Computation*, 10(4), 1762–1769. https://doi.org/10.1021/ct400977r |
| **[DEW1959]** | Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. *Numerische Mathematik*, 1, 269–271. https://doi.org/10.1007/BF01386390 |
| **[SO2018]** | Serçinoğlu, O., & Ozbek, P. (2018). gRINN: a tool for calculation of residue interaction energies and protein energy network analysis of molecular dynamics simulations. *Nucleic Acids Research*, 46(W1), W554–W562. https://doi.org/10.1093/nar/gky381 |

---

## 6. Exploring Results

### 6.1 Interactive Dashboard

When your job completes, click **Launch Dashboard** to open the interactive visualization interface.

The dashboard provides:

- **Pairwise Energies**: View interaction energies between specific residue pairs
- **Energy Matrix**: Heatmap visualization of the full interaction energy matrix
- **Network Analysis**: Protein energy network with centrality metrics
  - Degree centrality
  - Betweenness centrality
  - Closeness centrality
- **Shortest Path Analysis**: Find energy pathways between residue pairs
- **Integrated Molecular Viewer**: 3D protein structure visualization with Mol*
- **Integrated 3D Network Viewer**: Visual depiction of network nodes and edges with 3D-force-graph.
- **Frame slider**: A frame slider to which the dashboard UI elements respond interactively.

### 6.2 gRINN Chatbot: AI Chatbot Assistant

The dashboard includes an AI-powered chatbot (**gRINN Chatbot**) that enables natural language interaction with your analysis results. You can use plain English to query your data, generate custom visualizations, and explore complex relationships without writing code.

#### 6.2.1 How It Works

gRINN Chatbot uses [PandasAI](https://github.com/sinaptik-ai/pandas-ai) with [LiteLLM](https://github.com/BerriAI/litellm) to translate natural language queries into Python/pandas code that executes against your result DataFrames. The workflow is:

1. **You ask a question** in plain English (e.g., "Which residue has the highest betweenness centrality?")
2. **The LLM generates Python code** to answer your query using pandas operations
3. **The code executes** in a secure Docker sandbox environment
4. **Results are returned** as text, tables, or charts

#### 6.2.2 Available DataFrames

You can select up to **4 DataFrames** to include in your chat context. The available DataFrames depend on your analysis results:

| Category | DataFrames | Description |
|----------|------------|-------------|
| **Pairwise Energies** | IE_Total, IE_VdW, IE_Electrostatic | Per-frame interaction energies between all residue pairs (wide format: rows=pairs, columns=frames) |
| **Network Metrics** | Metrics_Total_Cov_Cut1.0, etc. | Per-frame centrality metrics (degree, betweenness, closeness) for each residue |

> **Note**: Edge DataFrames are excluded from the chatbot to reduce context size. Use the Network tab for edge-specific analysis.

#### 6.2.3 Filtering Options

To improve query performance and focus on relevant data, you can apply filters in the **Settings** panel:

- **DataFrame Selection**: Choose which DataFrames to include (max 4)
- **Residue Filter**: Limit analysis to specific residues (e.g., `GLY290_A, ASP45_B`)
- **Frame Range**: Analyze a subset of frames (e.g., frames 50–100)

A **stride** is automatically computed to keep the data within reasonable limits (~20 frames max) while preserving temporal coverage.

#### 6.2.4 Supported Models

gRINN Chatbot supports multiple LLM providers via LiteLLM:

| Provider | Example Models | API Key Environment Variable |
|----------|---------------|------------------------------|
| **Google** | `gemini/gemini-2.0-flash`, `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| **Anthropic** | `anthropic/claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |

The model can be selected from the **Model** dropdown in the chat settings panel.

#### 6.2.5 Example Queries

Here are some example queries you can ask:

**Basic Statistics:**
- "What is the average total interaction energy between all residue pairs?"
- "Which 10 residue pairs have the strongest attractive interactions?"
- "Show the distribution of electrostatic energies"

**Network Analysis:**
- "Which residue has the highest betweenness centrality on average?"
- "List the top 5 residues by degree centrality in frame 50"
- "How does closeness centrality change over time for residue GLY290_A?"

**Comparative Analysis:**
- "Compare the van der Waals and electrostatic contributions for the top 20 interacting pairs"
- "Are there any residues whose betweenness centrality increases significantly after frame 100?"

**Visualization:**
- "Plot the total interaction energy between ASP45_A and LYS120_B across all frames"
- "Create a bar chart of the top 10 residues by average degree centrality"
- "Show a heatmap of correlations between centrality metrics"

#### 6.2.6 Response Types

Depending on your query, gRINN Chatbot returns different response formats:

- **Text**: Narrative answers and explanations
- **Tables**: Pandas DataFrames displayed as formatted tables (limited to ~30 rows for display)
- **Charts**: Matplotlib visualizations embedded in the chat

Charts are stored in a **gallery** above the chat input and can be viewed again by clicking the numbered buttons.

#### 6.2.7 Token Usage & Limits

- Token usage is tracked per session and displayed in the chat header
- If a token limit is configured (via `PANDASAI_TOKEN_LIMIT`), queries will be blocked when the limit is reached
- Refresh the page to start a new session and reset the token counter

#### 6.2.8 Security

Generated code executes in a **Docker sandbox** (via [pandasai-docker](https://github.com/sinaptik-ai/pandasai-docker)) to prevent unauthorized access to the host system. The sandbox is started automatically when the chatbot is first used.

#### 6.2.9 Limitations

- **Context size**: Only up to 4 DataFrames can be included per query to manage token costs
- **Data scope**: The chatbot can only analyze DataFrames from gRINN output—it cannot access external data or files
- **Code execution**: While the sandbox provides security, complex or long-running computations may timeout
- **LLM variability**: Responses may vary between models and sessions; rephrasing queries can help if results are unexpected

---

## 7. Exporting & Downloading Results

### 7.1 Available Downloads

- The output folder populated by gRINN for each completed job can be downloaded as a .zip file on the Job Queue and Job Monitor pages.
- The output folder contains the following files:

#### 7.1.1 Energy Data Files

| File | Description |
|------|-------------|
| `energies_intEnTotal.csv` | Per-frame **total** (VdW + Electrostatic) pairwise interaction energies (kcal/mol). Wide format: rows = residue pairs, columns = frames. |
| `energies_intEnVdW.csv` | Per-frame **van der Waals** pairwise interaction energies (kcal/mol). |
| `energies_intEnElec.csv` | Per-frame **electrostatic** pairwise interaction energies (kcal/mol). |
| `average_interaction_energies.csv` | Time-averaged energies for each residue pair, including chain/residue metadata. |
| `energies_*.pickle` | Pickled Python dictionaries containing raw energy data (for programmatic access). |

#### 7.1.2 Protein Energy Network (PEN) Files

Located in the `pen_precomputed/` subfolder:

| File | Description |
|------|-------------|
| `manifest.json` | Metadata describing PEN parameters (cutoffs, energy types, frame counts). |
| `nodes.csv` | Residue node mapping with chain, residue name/number, and index information. |
| `metrics_{energy}_cov{0|1}_cutoff{X}.csv` | Per-frame centrality metrics (degree, betweenness, closeness) for each residue. Example: `metrics_Total_cov1_cutoff1.0.csv` |
| `edges_{energy}_cov{0|1}_cutoff{X}_frame{N}.csv` | Network edges for each frame, with weight and distance attributes. |

> **Note**: `cov1` = covalent bonds included; `cov0` = covalent bonds excluded.

#### 7.1.3 Structure & Topology Files

| File | Description |
|------|-------------|
| `system_dry.pdb` | Processed structure file (solvent/ions removed if applicable) used for analysis. |
| `topol_dry.top` | GROMACS topology file (provided or generated). |
| `traj_dry.xtc` | Processed trajectory (with frame skipping applied, if specified). |

#### 7.1.4 Log Files

| File | Description |
|------|-------------|
| `calc.log` | Detailed workflow log with timestamps and debug information. |
| `gromacs.log` | GROMACS command output and messages. |

### 7.2 Data Retention

- Job results are retained for **72 hours** (3 days) by default
- After expiration, files are deleted, but job records remain visible for a further **7 days**.
- Download your results before expiration to preserve them.

---

## 8. FAQ / Troubleshooting

### 8.1 General Questions

#### What is i-gRINN?

i-gRINN is an online tool for calculating residue interaction energies from biomolecular MD simulations and analyzing the resulting protein energy networks.

#### Do I need to install anything?

No, i-gRINN is entirely web-based and requires no installation. The analysis runs on servers provided by Gebze Technical University.

#### Which browsers are supported?

Modern versions of Chrome, Firefox, Edge, and Safari are fully supported.

#### Is there a cost to use i-gRINN?

i-gRINN is entirely free, although there are limitations applied to the input files to maintain accessibility of service.

### 8.2 Input Data Questions

#### What file formats are supported?

- **Structures**: PDB, GRO
- **Trajectories**: XTC, TRR
- **Topologies**: TOP
- **Archives**: ZIP (for force field folders)

#### Are there limits on file size or trajectory length?

- Maximum trajectory file size: 100 MB
- Maximum structure/topology file size: 10 MB
- For larger files, consider using the standalone gRINN tool

#### How do I prepare a multi-model PDB for Ensemble Mode?

Your PDB file should contain multiple conformations with this structure:

```
MODEL        1
ATOM      1  N   ALA A   1      ...
...
ENDMDL
MODEL        2
ATOM      1  N   ALA A   1      ...
...
ENDMDL
```

### 8.3 Analysis Questions

#### How long does an analysis take?

Typical analysis times:

- Small protein (< 200 residues), short trajectory: 5-15 minutes
- Medium protein (200-500 residues): 15-45 minutes
- Large protein (> 500 residues): 1-2 hours

Times vary based on trajectory length, number of frames analyzed, and server load.

#### What does the Skip Frames parameter do?

Skip Frames controls how many trajectory frames are analyzed. Setting it to 2 means every other frame is analyzed, reducing computation time by half. For initial exploration, higher skip values (5-10) can provide quick results.

#### What is the Initial Pair Filter Cutoff?

This distance cutoff (in Ångströms) determines which residue pairs are included in the analysis. Only pairs with at least one atom within this distance in any frame are analyzed. The default of 12.0 Å is suitable for most cases.

### 8.4 Results Questions

#### My job shows "Expired" status. What does this mean?

Expired jobs have passed the retention period (72 hours). The result files have been deleted to conserve storage. Job records remain visible but downloads and dashboard access are no longer available.

#### Can I download my results?

Yes, use the **Save Results** button to download a complete archive of all output files.

#### The dashboard won't load. What should I do?

- Ensure your job status is "Completed"
- Try refreshing the page
- Check that pop-ups are not blocked
- Contact support if issues persist

### 8.5 Common Issues

| Issue | Solution |
|-------|----------|
| Upload error | Ensure files match expected formats and size limits |
| Job stuck in "Pending" | Server may be busy; jobs are processed in queue order |
| Topology errors | Verify your TOP/TPR file matches the structure file |
| Missing residue parameters | Include required ITP files or force field folders |

---

## 9. Citation & References

If you use i-gRINN for research, please cite the following publication:

> Serçinoğlu, O., & Ozbek, P. (2018). gRINN: A tool for calculation of residue interaction energies and protein energy network analysis of molecular dynamics simulations. *Nucleic Acids Research*, 46(W1), W554–W562. https://doi.org/10.1093/nar/gky381

## 10. Contact & Support

i-gRINN is developed by the [Computational Structural Biology Research Group (COSTBIO)](https://costbio.github.io), Bioengineering Department, Gebze Technical University, in collaboration with the [Computational Biology and Bioinformatics Research Group](https://compbio-bioe-eng.marmara.edu.tr), Marmara University.

### 10.1 Getting Help

- **Bug Reports, Feature Requests**: Create issues at Github 
- **General Questions**: See FAQ above or contact us (see below)

### 10.2 Contact

For technical support or inquiries, contact Dr. Onur Serçinoğlu at

- Email: osercinoglu AT gtu DOT com / onursercin AT gmail DOT com


### 10.3 Acknowledgments

i-gRINN builds upon the standalone [gRINN](https://github.com/osercinoglu/grinn) tool and uses:

- **GROMACS** for pairwise non-bonded interaction energy calculations
- **Plotly Dash** for interactive visualizations
- **Mol*** for 3D molecular structure visualization
- **3D Force-Graph** for interactive network visualization
- **ProDy**, **mdtraj**, and **MDAnalysis** for simulation trajectory processing
- **PandasAI**, **LiteLLM**, and Gemini/Claude APIs for gRINN Chatbot functionality

The computing infrastructure is provided by the Bioengineering Department of Gebze Technical University.

© 2025 COSTBIO. All rights reserved.

---

*Last updated: December 2025*
