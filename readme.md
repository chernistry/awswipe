# 🧹 AWSwipe - Super AWS Resource Cleaner

![Project Banner](./assets/awswipe-logo.png)

**Effortlessly clean up AWS resources with AWSwipe – a powerful automation tool for AWS infrastructure cleanup.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)  
[![Issues](https://img.shields.io/github/issues/chernistry/awswipe)](https://github.com/chernistry/awswipe/issues)  
[![Version](https://img.shields.io/badge/Version-1.0.0-green.svg)](https://github.com/chernistry/awswipe/releases)

---

## 🚀 Overview
AWSwipe is an advanced Python-based tool designed to **automate the cleanup of AWS resources** across multiple regions. It helps in:

✅ Deleting orphaned AWS resources
✅ Managing AWS account hygiene efficiently
✅ Avoiding unnecessary costs due to unused AWS services
✅ Ensuring compliance with security best practices

---

## ⚙️ Features
| Feature | Description |
|---------|------------|
| 🌎 Multi-Region Support | Cleans up AWS resources across all available regions |
| 🔄 Automated Cleanup | Intelligent retry mechanism for failed deletions |
| 🔍 Logging & Reporting | Detailed logging and a final cleanup report |
| 🛠️ Customizable Execution | Choose specific regions or resource types to clean |
| 🔐 Secure Operations | Uses IAM role permissions to safely clean AWS |

---

## 🛠 Installation & Setup

### 📥 Prerequisites
- Python 3.8+
- AWS CLI configured with credentials
- Boto3 library installed

### 📌 Installation Steps
```sh
# Clone the repository
git clone https://github.com/chernistry/awswipe.git
cd awswipe

# Install dependencies
pip install -r requirements.txt
```

### 🏗️ Configuration
Ensure AWS credentials are configured:
```sh
aws configure
```
Or use an IAM role with appropriate permissions.

---

## 🚀 Usage
Run the script to clean all AWS regions:
```sh
python awswipe.py
```

To clean a specific AWS region:
```sh
python awswipe.py --region us-east-1
```

Enable verbose logging:
```sh
python awswipe.py -v
```

---

## 📊 Cleanup Report Example
```
=== AWS Super Cleanup Report ===

Resource: S3 Buckets
  Deleted:
    - my-unused-bucket
  Failed:
    None

Resource: EC2 Instances
  Deleted:
    - i-0abc123def456gh78
  Failed:
    - i-09xyz987lmn654pq (Permission Denied)
```

---

## 🛠 Troubleshooting
| Issue | Resolution |
|--------|------------|
| `botocore.exceptions.NoCredentialsError` | Run `aws configure` to set credentials |
| `Permission Denied` | Ensure the IAM role has sufficient delete permissions |
| `ThrottlingException` | AWS rate limits apply, retry later |

---

## 🤝 Contributing
Want to improve AWSwipe? Follow these steps:
1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature-new-enhancement`
3. **Commit** your changes: `git commit -m 'Add new feature'`
4. **Push** to GitHub: `git push origin feature-new-enhancement`
5. **Open a Pull Request**

---

## 📜 License
AWSwipe is licensed under the **MIT License**. 

---

## 📢 Contact & Community
Created by **Alexander (Sasha) Chernysh**  
GitHub: [chernistry](https://github.com/chernistry)  
Got questions? Open an [issue](https://github.com/chernistry/awswipe/issues) or start a discussion!

