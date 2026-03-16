"""
Wallet Invariant MVP - CLI 工具

命令：
- gate eval --tx-hash <hash>: 评估单笔交易
- gate batch --input <file>: 批量评估
- gate report --input <file> --output <file>: 生成报告
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from .config import GateConfig
from .gate import ExecutionGate
from .evaluation import Evaluator, load_dataset

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@click.group()
@click.option("--rpc-url", envvar="RPC_URL", help="RPC endpoint URL")
@click.option("--debug/--no-debug", default=False, help="Enable debug mode")
@click.option("--enable-trace/--no-trace", default=False, help="Enable trace collection")
@click.pass_context
def cli(ctx, rpc_url: Optional[str], debug: bool, enable_trace: bool):
    """Wallet Invariant Gate - 交易准入裁决工具"""
    ctx.ensure_object(dict)
    
    config = GateConfig.from_env()
    if rpc_url:
        config.simulator.rpc_url = rpc_url
    config.debug = debug
    config.simulator.enable_trace = enable_trace
    
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    ctx.obj["config"] = config


@cli.command()
@click.option("--tx-hash", "-t", required=True, help="Transaction hash to evaluate")
@click.option("--output", "-o", type=click.Path(), help="Output file path (JSON)")
@click.option("--format", "-f", type=click.Choice(["json", "summary"]), default="summary")
@click.pass_context
def eval(ctx, tx_hash: str, output: Optional[str], format: str):
    """评估单笔交易"""
    config: GateConfig = ctx.obj["config"]
    
    if not config.simulator.rpc_url:
        click.echo("错误: 未配置 RPC URL。使用 --rpc-url 或设置 RPC_URL 环境变量", err=True)
        sys.exit(1)
    
    async def run():
        gate = ExecutionGate(config)
        
        click.echo(f"正在评估交易: {tx_hash}")
        
        try:
            decision = await gate.evaluate_tx_hash(tx_hash)
        except Exception as e:
            click.echo(f"评估失败: {e}", err=True)
            sys.exit(1)
        
        if format == "json":
            result = decision.to_json(indent=2)
            if output:
                Path(output).write_text(result, encoding="utf-8")
                click.echo(f"结果已保存到: {output}")
            else:
                click.echo(result)
        else:
            # Summary 格式
            click.echo("\n" + "=" * 50)
            click.echo(f"裁决结果: {decision.decision.value.upper()}")
            click.echo("=" * 50)
            
            if decision.is_fail_open:
                click.echo(f"⚠️  Fail-open: {decision.fail_open_reason.value if decision.fail_open_reason else 'unknown'}")
                if decision.fail_open_details:
                    click.echo(f"   详情: {decision.fail_open_details}")
            
            if decision.violations:
                click.echo("\n违规记录:")
                for v in decision.violations:
                    click.echo(f"  - [{v.invariant_id.value}] {v.message}")
            
            if decision.risk_labels:
                click.echo("\n风险标签:")
                for r in decision.risk_labels:
                    click.echo(f"  - [{r.severity}] {r.label}")
            
            if decision.delta_summary:
                summary = decision.delta_summary.get("summary", {})
                click.echo("\n状态变化摘要:")
                click.echo(f"  - 有资产流出: {summary.get('has_outflow', False)}")
                click.echo(f"  - 有新无限授权: {summary.get('has_new_unlimited_permission', False)}")
            
            click.echo("")
    
    asyncio.run(run())


@cli.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), 
              help="Input dataset file (JSON)")
@click.option("--output", "-o", type=click.Path(), help="Output report file (JSON)")
@click.option("--concurrency", "-c", default=5, help="Number of concurrent evaluations")
@click.pass_context
def batch(ctx, input_file: str, output: Optional[str], concurrency: int):
    """批量评估交易"""
    config: GateConfig = ctx.obj["config"]
    
    if not config.simulator.rpc_url:
        click.echo("错误: 未配置 RPC URL。使用 --rpc-url 或设置 RPC_URL 环境变量", err=True)
        sys.exit(1)
    
    # 加载数据集
    try:
        samples = load_dataset(input_file)
    except Exception as e:
        click.echo(f"加载数据集失败: {e}", err=True)
        sys.exit(1)
    
    click.echo(f"加载了 {len(samples)} 个样本")
    
    async def run():
        evaluator = Evaluator(config)
        
        def progress(current, total, result):
            status = "✓" if result.decision.decision.value == "allow" else "✗"
            click.echo(f"[{current}/{total}] {status} {result.sample.tx_hash[:16]}...")
        
        report = await evaluator.run_evaluation(
            samples,
            concurrency=concurrency,
            progress_callback=progress,
        )
        
        # 输出摘要
        click.echo("\n" + report.summary())
        
        # 保存报告
        if output:
            report.save(output)
            click.echo(f"\n报告已保存到: {output}")
    
    asyncio.run(run())


@cli.command()
@click.option("--output", "-o", type=click.Path(), default="sample_dataset.json",
              help="Output file path")
def init_dataset(output: str):
    """初始化示例数据集"""
    samples = [
        {
            "tx_hash": "0x0000000000000000000000000000000000000000000000000000000000000001",
            "label": "attack",
            "description": "示例攻击交易（需替换为真实 txHash）",
            "expected_decision": "reject",
        },
        {
            "tx_hash": "0x0000000000000000000000000000000000000000000000000000000000000002",
            "label": "benign",
            "description": "示例正常交易（需替换为真实 txHash）",
            "expected_decision": "allow",
        },
    ]
    
    data = {"samples": samples}
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    click.echo(f"示例数据集已创建: {output}")
    click.echo("请编辑文件，替换为真实的交易哈希。")


@cli.command()
def version():
    """显示版本信息"""
    from . import __version__
    click.echo(f"Wallet Invariant MVP v{__version__}")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
