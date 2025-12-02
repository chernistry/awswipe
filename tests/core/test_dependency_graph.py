import pytest
from awswipe.core.dependency_graph import DependencyGraph

def test_dependency_graph_simple():
    graph = DependencyGraph()
    graph.add_node('vpc', ['ec2']) # VPC depends on EC2 (EC2 must run first)
    # Wait, my logic was: "A depends on B" -> B must run before A.
    # In my implementation:
    # add_node('vpc', ['ec2']) -> prerequisites['vpc'] = ['ec2']
    # adj['ec2'].append('vpc')
    # in_degree['vpc'] += 1
    # queue starts with 'ec2' (in-degree 0)
    # pop 'ec2', result=['ec2']
    # decrement 'vpc' in-degree to 0, push 'vpc'
    # result=['ec2', 'vpc']
    # So execution order: EC2, then VPC.
    # This matches "VPC depends on EC2" (EC2 must be deleted first).
    
    order = graph.get_execution_order()
    assert order == ['ec2', 'vpc']

def test_dependency_graph_complex():
    graph = DependencyGraph()
    graph.add_node('vpc', ['ec2', 'elb'])
    graph.add_node('ec2', ['ebs']) # Wait, EC2 depends on EBS? No, EBS depends on EC2 (detach).
    # If EBS depends on EC2, then EC2 runs first.
    # So graph.add_node('ebs', ['ec2'])
    
    # Let's fix the test case to match reality
    # EC2 instances use EBS volumes. We terminate instances, then delete volumes.
    # So EBS deletion depends on EC2 termination.
    # EBS cleaner prerequisites = ['ec2']
    
    graph = DependencyGraph()
    graph.add_node('ebs', ['ec2'])
    graph.add_node('vpc', ['ec2', 'ebs', 'elb'])
    graph.add_node('elb', ['ec2'])
    
    # Expected: EC2 (no prereqs) -> ELB/EBS (prereq EC2) -> VPC (prereq all)
    order = graph.get_execution_order()
    
    assert order.index('ec2') < order.index('ebs')
    assert order.index('ec2') < order.index('elb')
    assert order.index('ec2') < order.index('vpc')
    assert order.index('ebs') < order.index('vpc')
    assert order.index('elb') < order.index('vpc')

def test_dependency_graph_cycle():
    graph = DependencyGraph()
    graph.add_node('a', ['b'])
    graph.add_node('b', ['a'])
    
    order = graph.get_execution_order()
    # Should return all nodes even with cycle (fallback)
    assert set(order) == {'a', 'b'}
    assert len(order) == 2
