from lxml import etree
import pandas as pd
import os
import sys

# 函数：递归获取所有以 TEST 开头的 XML 文件
def get_all_xml_files(directory):
    xml_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.startswith('TEST') and file.endswith('.xml'):
                xml_files.append(os.path.join(root, file))
    return xml_files

def main():
    # 检查是否提供目录参数
    if len(sys.argv) < 2:
        print("Usage: python script.py <directory>")
        sys.exit(1)

    directory = sys.argv[1]

    # 收集所有符合条件的 XML 文件
    xml_files = get_all_xml_files(directory)

    if not xml_files:
        print("No XML files starting with 'TEST' found in the specified directory.")
        sys.exit(0)

    data = []
    
    # 解析每个 XML 文件并提取所需信息
    for p in xml_files:
        try:
            tree = etree.parse(p)
            tests = int(tree.xpath('/testsuite/@tests')[0]) if tree.xpath('/testsuite/@tests') else 0
            failures = int(tree.xpath('/testsuite/@failures')[0]) if tree.xpath('/testsuite/@failures') else 0
            errors = int(tree.xpath('/testsuite/@errors')[0]) if tree.xpath('/testsuite/@errors') else 0
            data.append((p, tests, failures, errors))
        except Exception as e:
            print(f"Error parsing file {p}: {e}")

    # 创建 DataFrame
    df = pd.DataFrame(data, columns=["Path", "NumTests", "NumFails", "NumErrs"])

    # 添加总计行
    if not df.empty:
        sum_row = pd.DataFrame(df[['NumTests', 'NumFails', 'NumErrs']].sum()).T
        sum_row['Path'] = 'Total'
        df = pd.concat([df, sum_row], ignore_index=True).sort_values("NumTests")

    # 输出结果到终端并保存为 CSV 文件
    with pd.option_context('display.max_rows', None, 'display.max_colwidth', None):
        print(df)

    output_file = os.path.join(directory, "test_summary.csv")
    df.to_csv(output_file, index=False)
    print(f"Summary saved to {output_file}")

if __name__ == "__main__":
    main()