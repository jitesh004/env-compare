import os
import hcl2
from deepdiff import DeepDiff
import json
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Define an array of all environment-specific keys
environment_specific_keys = [
    "uri",
    "environment",
    "env",
    "url",
    "endpoint",
    "life_cycle",
    "arn"
]

def parse_tfvars(file_path):
    try:
        with open(file_path, 'r') as file:
            data = hcl2.load(file)
            return data
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error parsing {file_path}: {str(e)}")
        sys.exit(1)

def is_environment_specific(key, env1='', env2=''):
    environment_indicators = [env1.lower(), env2.lower(), "acnt", "acpt", "cont", "dev1", "prod"]

    if any(indicator in key.lower() for indicator in environment_indicators):
        return True

    # Check if the key belongs to the environment-specific keys array
    if any(es_key in key.lower() for es_key in environment_specific_keys):
        return True

    return False

def extract_diff(diff, value1, value2, key_path):
    def format_key(path):
        return path.replace("root.", "").replace("[", ".").replace("]", "").replace("", "")

    def handle_nested_diffs(old_value, new_value, base_key=""):
        diffs = []
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            for k, v in old_value.items():
                if k in new_value and new_value[k] != v:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.extend(handle_nested_diffs(v, new_value[k], nested_key))
                elif k not in new_value:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.append(f"{nested_key}: {v} was removed")
            for k, v in new_value.items():
                if k not in old_value:
                    nested_key = f"{base_key}.{k}" if base_key else k
                    diffs.append(f"{nested_key}: {v} was added")
        elif isinstance(old_value, list) and isinstance(new_value, list):
            for i, (old_item, new_item) in enumerate(zip(old_value, new_value)):
                if old_item != new_item:
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.extend(handle_nested_diffs(old_item, new_item, nested_key))
            if len(old_value) < len(new_value):
                for i in range(len(old_value), len(new_value)):
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.append(f"{nested_key}: {new_value[i]} was added")
            elif len(old_value) > len(new_value):
                for i in range(len(new_value), len(old_value)):
                    nested_key = f"{base_key}[{i}]" if base_key else str(i)
                    diffs.append(f"{nested_key}: {old_value[i]} was removed")
        else:
            diffs.append(f"{base_key}: {old_value} => {new_value}")
        return diffs

    if "values_changed" in diff:
        changes = diff["values_changed"]
        diffs = []
        for path, change in changes.items():
            old_value = change["old_value"]
            new_value = change["new_value"]
            key = format_key(path)
            diffs.extend(handle_nested_diffs(old_value, new_value, key))
        return "\\n".join(diffs)
    elif "iterable_item_removed" in diff or "iterable_item_added" in diff:
        diffs = []
        for change_type in ["iterable_item_removed", "iterable_item_added"]:
            if change_type in diff:
                for path, change in diff[change_type].items():
                    key = format_key(path)
                    diffs.append(f"{key}: {change} was {change_type.replace('iterable_item_', '')}")
        return "\\n".join(diffs)
    else:
        return f"{value1} => {value2}"

def compare_tfvars_data(data1, data2, env1, env2):
    try:
        all_keys = set(data1.keys()).union(set(data2.keys()))
        all_keys = sorted(all_keys, key=str.lower)
        comparison_results = []
        summary = {
            "equal": 0,
            "undefined": 0,
            "red": 0,
            "blue": 0
        }
        for key in all_keys:
            value1 = data1.get(key, "undefined")
            value2 = data2.get(key, "undefined")
            key_path = key

            if value1 != "undefined" and value2 != "undefined":
                diff = DeepDiff(value1, value2, ignore_order=True)
                if diff:
                    exact_diff = extract_diff(diff, value1, value2, key_path)
                    row_class = "blue" if is_environment_specific(key_path, env1, env2) else "red"
                    status = "Values differ but seems fine for different environments, please verify" if row_class == "blue" else "Unexpected difference, please review"
                    summary["blue" if row_class == "blue" else "red"] += 1
                else:
                    exact_diff = ""
                    row_class = "equal"
                    status = "Equal"
                    summary["equal"] += 1
            elif value1 == "undefined":
                exact_diff = f"{key} is not defined in {env1.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env1.upper()}"
                summary["undefined"] += 1
            else:
                exact_diff = f"{key} is not defined in {env2.upper()}"
                row_class = "yellow"
                status = f"Not defined in {env2.upper()}"
                summary["undefined"] += 1
            comparison_results.append((key, json.dumps(value1, indent=2), json.dumps(value2, indent=2), exact_diff, row_class, status))
        return comparison_results, summary
    except Exception as e:
        logging.error(f"Error during comparison: {str(e)}")
        sys.exit(1)

def escape_html(text):
    escape_table = {
        "&": "&amp;",
        "\"": "&quot;",
        "'": "&#x27;",
        ">": "&gt;",
        "<": "&lt;"
    }
    return "".join(escape_table.get(c, c) for c in text)

def write_comparison_to_html(comparison_results, summary, template_path, output_file, env1, env2, branch_name, commit_id, commit_message, file1_path, file2_path):
    try:
        with open(template_path, 'r') as template_file:
            template = template_file.read()
        summary_html = (
            "<h2>Summary</h2>"
            f"<p><strong>Branch:</strong> {escape_html(branch_name)}</p>"
            f"<p><strong>Latest Commit:</strong> {escape_html(commit_id)}</p>"
            f"<p><strong>Comparing Files:</strong> {file1_path} & {file2_path}</p>"
            f"<p><strong>Comparing Envs:</strong> {env1.upper()} & {env2.upper()}</p>"
            f"<p><strong><span style='color: #3cc257;'>&#9679;</span> Equal Variables:</strong> {summary['equal']}</p>"
            f"<p><strong><span style='color: rgb(241, 83, 83);'>&#9679;</span> Red Variables (Check Required):</strong> {summary['red']}</p>"
            f"<p><strong><span style='color: rgb(26, 179, 230);'>&#9679;</span> Blue Variables (Environment Specific):</strong> {summary['blue']}</p>"
        )
        rows = ""
        for key, value1, value2, exact_diff, row_class, status in comparison_results:
            value1 = escape_html(value1)
            value2 = escape_html(value2)
            exact_diff = escape_html(exact_diff).replace("root: ", "")
            rows += (
                f"<tr class='{row_class}'>"
                f"<td>{escape_html(key)}</td>"
                f"<td><pre>{value1}</pre></td>"
                f"<td><pre>{value2}</pre></td>"
                f"<td><pre style='word-break: break-all;'>{exact_diff}</pre></td>"
                f"<td class='status'>{status}</td>"
                "</tr>"
            )
        html_content = template
        html_content = html_content.replace("{summary}", summary_html)
        html_content = html_content.replace("{env1}", env1.upper())
        html_content = html_content.replace("{env2}", env2.upper())
        html_content = html_content.replace("{rows}", rows)
        with open(output_file, 'w') as file:
            file.write(html_content)
        logging.info(f"Comparison report successfully written to {output_file}")
    except FileNotFoundError:
        logging.error(f"Template file not found: {template_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error writing to HTML file {output_file}: {str(e)}")
        sys.exit(1)

def main(env1, env2, template_path, output_file, config_directory_path, branch_name, commit_id, commit_message):
    try:
        file1_path = f"{config_directory_path}/workspace_vars.{env1.lower()}.tfvars"
        file2_path = f"{config_directory_path}/workspace_vars.{env2.lower()}.tfvars"

        if not os.path.exists(file1_path):
            logging.error(f"File not found: {file1_path}")
            sys.exit(1)
        if not os.path.exists(file2_path):
            logging.error(f"File not found: {file2_path}")
            sys.exit(1)

        data1 = parse_tfvars(file1_path)
        data2 = parse_tfvars(file2_path)

        comparison_results, summary = compare_tfvars_data(data1, data2, env1, env2)
        write_comparison_to_html(comparison_results, summary, template_path, output_file, env1, env2, branch_name, commit_id, commit_message, file1_path, file2_path)

        logging.info(f"Comparison report generated: {output_file}")
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 9:
        logging.error("Usage: python compare_tfvars.py <env1> <env2> <template_path> <output_file> <config_directory_path> <branch_name> <commit_id> <commit_message>")
        logging.error("Example: python compare_tfvars.py acpt prod template.html output.html tf main abc123 'Initial commit'")
        sys.exit(1)

    env1 = sys.argv[1]
    env2 = sys.argv[2]
    template_path = sys.argv[3]
    output_file = sys.argv[4]
    config_directory_path = sys.argv[5]
    branch_name = sys.argv[6]
    commit_id = sys.argv[7]
    commit_message = sys.argv[8]

    logging.info(f"env1: {env1}, env2: {env2}, config_directory_path: {config_directory_path}, template_path: {template_path}, output_file: {output_file}, branch: {branch_name}, commit_id: {commit_id}, commit_message: {commit_message}")

    main(env1, env2, template_path, output_file, config_directory_path, branch_name, commit_id, commit_message)
"""